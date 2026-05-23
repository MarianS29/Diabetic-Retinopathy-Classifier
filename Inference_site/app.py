import os
import sys
import time
import base64
from io import BytesIO
import torch
import torch.nn.functional as F
from torchvision import transforms
import numpy as np
from PIL import Image, ImageOps, ImageFilter
from flask import Flask, request, jsonify
from flask_cors import CORS

# Adaugam calea catre notebook-uri pentru a putea importa get_model din builder.py
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SYS_PATH_TO_BUILDER = os.path.join(BASE_DIR, "Notebooks")
if SYS_PATH_TO_BUILDER not in sys.path:
    sys.path.insert(0, SYS_PATH_TO_BUILDER)

from builder import get_model

app = Flask(__name__)
CORS(app) # Permitem comunicarea cu frontend-ul pe un port diferit

MODELS_DIR = os.path.join(BASE_DIR, "Notebooks", "Clasificare_datasets_balanced", "Rezultate", "modele")
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# Definim recomandarile in functie de stadiu
RECOMMENDATIONS = {
    0: {
        "name": "Fara Retinopatie (No DR)",
        "patient": "Mentineti un stil de viata sanatos si veniti la un control de rutina o data pe an.",
        "doctor": "Nu se observa anomalii pe fundul de ochi. Programare pentru control anual."
    },
    1: {
        "name": "Retinopatie Usoara (Mild)",
        "patient": "Este necesar controlul strict al glicemiei si dietei. Reveniti la control in 6-12 luni.",
        "doctor": "Prezenta microanevrismelor. Nu necesita tratament oftalmologic imediat, doar optimizare metabolica."
    },
    2: {
        "name": "Retinopatie Moderata (Moderate)",
        "patient": "Sunt necesare controale oftalmologice mai dese (la 3-6 luni) si analize detaliate.",
        "doctor": "Se recomanda evaluare atenta pentru identificarea unui potential edem macular clinic semnificativ."
    },
    3: {
        "name": "Retinopatie Severa (Severe)",
        "patient": "Stare avansata. Trebuie sa urmati tratamentul cu strictete si sa efectuati analize de urgenta.",
        "doctor": "Risc crescut de progresie catre faza proliferativa. Recomandata Angiofluorografie si monitorizare stransa."
    },
    4: {
        "name": "Retinopatie Proliferativa (Proliferative)",
        "patient": "Situatie critica pentru vedere. Poate fi necesara interventie cu laser sau operatie. Prezentati-va urgent la specialist.",
        "doctor": "Se impune fotocoagulare panretiniana (PRP) sau interventie chirurgicala. Trimitere urgenta la specialist retinolog."
    }
}

def get_base_model_name(filename):
    # Extrage tipul de retea din numele modelului salvat (ex: 'best_resnet50_ce_adam_LR_0.0001.pth' -> 'resnet50')
    name = filename.lower()
    if 'incres_v2' in name or 'inception_resnet_v2' in name: return 'incres_v2'
    if 'resnet50' in name: return 'resnet50'
    if 'efficientnet_b3' in name: return 'efficientnet_b3'
    if 'efficientnet_b0' in name: return 'efficientnet_b0'
    if 'densenet121' in name: return 'densenet121'
    if 'inception_v3' in name: return 'inception_v3'
    return 'resnet50' # Default fallback

def get_input_size(base_arch):
    if base_arch in ('inception_v3', 'incres_v2'):
        return 299
    return 224

def image_to_data_url(image):
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode('ascii')
    return f"data:image/png;base64,{encoded}"

def crop_dark_border(image, threshold=12):
    arr = np.asarray(image)
    mask = arr.mean(axis=2) > threshold
    if not mask.any():
        return image

    y_idx, x_idx = np.where(mask)
    top, bottom = y_idx.min(), y_idx.max()
    left, right = x_idx.min(), x_idx.max()
    return image.crop((left, top, right + 1, bottom + 1))

def pad_to_square(image, fill=(0, 0, 0)):
    width, height = image.size
    size = max(width, height)
    canvas = Image.new('RGB', (size, size), fill)
    offset = ((size - width) // 2, (size - height) // 2)
    canvas.paste(image, offset)
    return canvas

def apply_ben_graham_like(image, output_size):
    image = crop_dark_border(image)
    image = pad_to_square(image)
    image = image.resize((output_size, output_size), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(image, cutoff=1)

    arr = np.asarray(image).astype(np.float32)
    blurred = np.asarray(image.filter(ImageFilter.GaussianBlur(radius=max(output_size / 30, 6)))).astype(np.float32)
    enhanced = (4.0 * arr) + (-4.0 * blurred) + 128.0
    enhanced = np.clip(enhanced, 0, 255).astype(np.uint8)
    return Image.fromarray(enhanced, mode='RGB')

def should_preprocess_fundus(image):
    arr = np.asarray(image.resize((256, 256), Image.Resampling.BILINEAR)).astype(np.uint8)
    gray = arr.mean(axis=2)
    dark_ratio = float((gray < 18).mean())
    width, height = image.size
    aspect_delta = abs(width - height) / max(width, height)
    border = np.concatenate([gray[:12, :].ravel(), gray[-12:, :].ravel(), gray[:, :12].ravel(), gray[:, -12:].ravel()])
    dark_border_ratio = float((border < 18).mean())

    # Imaginile brute EyePACS/APTOS au frecvent fundal negru extins sau format nepătrat.
    should_apply = dark_ratio > 0.18 or dark_border_ratio > 0.35 or aspect_delta > 0.08
    reason = "preprocesare aplicata: margini intunecate/aspect brut detectat" if should_apply else "imaginea pare deja preprocesata"
    return should_apply, {
        "applied": should_apply,
        "reason": reason,
        "dark_ratio": dark_ratio,
        "dark_border_ratio": dark_border_ratio,
        "aspect_delta": aspect_delta,
    }

def count_parameters(model):
    total = sum(param.numel() for param in model.parameters())
    trainable = sum(param.numel() for param in model.parameters() if param.requires_grad)
    return total, trainable

def format_size(size):
    width, height = size
    return f"{width} x {height} px"

@app.route('/api/models', methods=['GET'])
def get_models():
    if not os.path.exists(MODELS_DIR):
        return jsonify({"models": [], "error": f"Folderul nu a fost gasit: {MODELS_DIR}"})
    
    models = [f for f in os.listdir(MODELS_DIR) if f.endswith('.pth')]
    return jsonify({"models": models})

@app.route('/api/predict', methods=['POST'])
def predict():
    if 'image' not in request.files or 'model_name' not in request.form:
        return jsonify({"error": "Imaginea si numele modelului sunt obligatorii."}), 400

    file = request.files['image']
    model_name = request.form['model_name']
    model_path = os.path.join(MODELS_DIR, model_name)

    if not os.path.exists(model_path):
        return jsonify({"error": "Modelul selectat nu exista pe disc."}), 404

    try:
        image = Image.open(file.stream).convert('RGB')
        original_image_size = image.size
        base_arch = get_base_model_name(model_name)
        input_size = get_input_size(base_arch)
        should_apply_preprocessing, preprocessing_info = should_preprocess_fundus(image)
        inference_image = apply_ben_graham_like(image, input_size) if should_apply_preprocessing else image.resize((input_size, input_size), Image.Resampling.LANCZOS)

        transform = transforms.Compose([
            transforms.Resize((input_size, input_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                 std=[0.229, 0.224, 0.225])
        ])
        input_tensor = transform(inference_image).unsqueeze(0).to(DEVICE)

        # Incarca modelul potrivit
        model_load_start = time.perf_counter()
        model = get_model(base_arch, num_classes=5, pretrained=False)

        if model is None:
            return jsonify({"error": f"Eroare: get_model a returnat None pentru arhitectura '{base_arch}'. Verifica importurile in builder.py!"}), 500

        model.load_state_dict(torch.load(model_path, map_location=DEVICE))
        model = model.to(DEVICE)
        model.eval()
        model_load_time_ms = (time.perf_counter() - model_load_start) * 1000
        parameter_count, trainable_parameter_count = count_parameters(model)

        # Evaluare si timing
        start_time = time.perf_counter()
        with torch.no_grad():
            outputs = model(input_tensor)
            probs = F.softmax(outputs, dim=1)[0]
            confidence, predicted_class = torch.max(probs, 0)
        end_time = time.perf_counter()

        predicted_class = predicted_class.item()
        confidence = confidence.item()
        inference_time_ms = (end_time - start_time) * 1000
        sorted_probs = torch.sort(probs, descending=True).values
        top2_margin = float(sorted_probs[0] - sorted_probs[1]) if sorted_probs.numel() > 1 else 0.0

        rec = RECOMMENDATIONS.get(predicted_class, RECOMMENDATIONS[0])

        response = {
            "stage": predicted_class,
            "stage_name": rec["name"],
            "confidence": float(confidence),
            "recommendations": {
                "patient": rec["patient"],
                "doctor": rec["doctor"]
            },
            "model_data": {
                "model_name": model_name,
                "inference_time_ms": inference_time_ms,
                "model_load_time_ms": model_load_time_ms,
                "device": str(DEVICE),
                "cuda_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                "raw_probabilities": [float(p) for p in probs.cpu().numpy()],
                "input_size": input_size,
                "architecture": base_arch,
                "original_image_size": format_size(original_image_size),
                "inference_image_size": format_size(inference_image.size),
                "model_file_size_mb": os.path.getsize(model_path) / (1024 * 1024),
                "parameter_count": parameter_count,
                "trainable_parameter_count": trainable_parameter_count,
                "top2_margin": top2_margin,
                "normalization": {
                    "mean": [0.485, 0.456, 0.406],
                    "std": [0.229, 0.224, 0.225],
                },
            },
            "preprocessing": preprocessing_info,
            "processed_image": image_to_data_url(inference_image),
        }
        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
