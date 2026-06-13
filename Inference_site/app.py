import os
import sys
import time
import base64
import importlib.util
from io import BytesIO
import cv2
import torch
import torch.nn.functional as F
from torchvision import transforms
import numpy as np
from PIL import Image
from flask import Flask, request, jsonify
from flask_cors import CORS

# Adaugam calea catre notebook-uri pentru a putea importa get_model din builder.py
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SYS_PATH_TO_BUILDER = os.path.join(BASE_DIR, "Notebooks", "Main")
BUILDER_PATH = os.path.join(SYS_PATH_TO_BUILDER, "builder.py")
if SYS_PATH_TO_BUILDER not in sys.path:
    sys.path.insert(0, SYS_PATH_TO_BUILDER)

def load_builder():
    if not os.path.exists(BUILDER_PATH):
        raise RuntimeError(f"Nu pot gasi builder.py la: {BUILDER_PATH}")

    spec = importlib.util.spec_from_file_location("builder", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Nu pot incarca builder.py: {BUILDER_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "get_model"):
        raise RuntimeError("builder.py nu contine functia get_model.")

    return module

builder = load_builder()
get_model = builder.get_model

app = Flask(__name__)
CORS(app) # Permitem comunicarea cu frontend-ul pe un port diferit

EXPERIMENT_MODELS_DIR = os.path.join(BASE_DIR, "Notebooks", "Rezultate", "New", "modele")
MAIN_MODELS_DIR = os.path.join(BASE_DIR, "Notebooks", "Main", "Local")
MAIN_DETECTOR_FILENAME = "efficientnet_b3_binar_best.pth"
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

def pil_to_bgr(image):
    rgb = np.asarray(image.convert('RGB'))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

def preprocess_like_training_scripts(image, size=512):
    bgr_image = pil_to_bgr(image)
    resized = cv2.resize(bgr_image, (size, size), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (0, 0), sigmaX=size / 30)
    ben_graham = cv2.addWeighted(gray, 4, blur, -4, 128)
    _, mask = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    processed = np.zeros_like(ben_graham)

    if contours:
        contour = max(contours, key=cv2.contourArea)
        retina_mask = np.zeros_like(gray)
        cv2.drawContours(retina_mask, [contour], -1, 255, thickness=-1)
        processed[retina_mask == 255] = ben_graham[retina_mask == 255]
    else:
        processed = ben_graham

    processed_rgb = cv2.cvtColor(processed, cv2.COLOR_GRAY2RGB)
    processed_pil = Image.fromarray(processed_rgb, mode='RGB')
    dark_ratio = float((gray < 18).mean())
    border = np.concatenate([gray[:12, :].ravel(), gray[-12:, :].ravel(), gray[:, :12].ravel(), gray[:, -12:].ravel()])
    dark_border_ratio = float((border < 18).mean())
    width, height = image.size
    aspect_delta = abs(width - height) / max(width, height)

    return processed_pil, {
        "applied": True,
        "method": "Ben Graham + masca retina",
        "reason": "preprocesare aplicata pentru uniformizarea imaginilor fundus inainte de inferenta",
        "processing_size": size,
        "dark_ratio": dark_ratio,
        "dark_border_ratio": dark_border_ratio,
        "aspect_delta": aspect_delta,
    }

def legacy_unused_preprocess_detection(image):
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

def list_pth_files(folder):
    if not os.path.exists(folder):
        return []
    return sorted([f for f in os.listdir(folder) if f.lower().endswith('.pth')])

def find_main_stage2_model():
    candidates = []
    for filename in list_pth_files(MAIN_MODELS_DIR):
        lowered = filename.lower()
        if filename == MAIN_DETECTOR_FILENAME:
            continue
        if any(token in lowered for token in ("stage2", "severitate", "severity", "1_4", "1-4", "clasificare")):
            candidates.append(filename)
    return candidates[0] if candidates else None

def build_model_option(model_id, label, group, mode, filename=None, architecture=None, available=True):
    return {
        "id": model_id,
        "label": label,
        "group": group,
        "mode": mode,
        "filename": filename,
        "architecture": architecture,
        "available": available,
    }

def get_model_catalog():
    models = []
    groups = [
        {"id": "main", "label": "Modele principale"},
        {"id": "experiments", "label": "Experimente"},
    ]

    detector_path = os.path.join(MAIN_MODELS_DIR, MAIN_DETECTOR_FILENAME)
    stage2_filename = find_main_stage2_model()
    main_available = os.path.exists(detector_path)
    main_label = "Pipeline principal: detectie + clasificare 1-4" if stage2_filename else "Pipeline principal: detectie binara"
    models.append(build_model_option(
        "main:pipeline",
        main_label,
        "main",
        "pipeline",
        filename=MAIN_DETECTOR_FILENAME,
        architecture="efficientnet_b3",
        available=main_available,
    ))

    for filename in list_pth_files(EXPERIMENT_MODELS_DIR):
        arch = get_base_model_name(filename)
        models.append(build_model_option(
            f"exp:{filename}",
            filename,
            "experiments",
            "multiclass",
            filename=filename,
            architecture=arch,
        ))

    return groups, models

def resolve_model_selection(model_id):
    if model_id == "main:pipeline":
        detector_path = os.path.join(MAIN_MODELS_DIR, MAIN_DETECTOR_FILENAME)
        if not os.path.exists(detector_path):
            raise FileNotFoundError(f"Modelul principal de detectie nu exista: {detector_path}")

        stage2_filename = find_main_stage2_model()
        stage2_path = os.path.join(MAIN_MODELS_DIR, stage2_filename) if stage2_filename else None
        return {
            "id": model_id,
            "mode": "pipeline",
            "detector_path": detector_path,
            "detector_name": MAIN_DETECTOR_FILENAME,
            "detector_arch": "efficientnet_b3",
            "stage2_path": stage2_path,
            "stage2_name": stage2_filename,
            "stage2_arch": get_base_model_name(stage2_filename) if stage2_filename else None,
        }

    if model_id.startswith("exp:"):
        filename = model_id.split(":", 1)[1]
        model_path = os.path.join(EXPERIMENT_MODELS_DIR, filename)
        if not os.path.exists(model_path):
            raise FileNotFoundError("Modelul experimental selectat nu exista pe disc.")
        return {
            "id": model_id,
            "mode": "multiclass",
            "model_path": model_path,
            "model_name": filename,
            "architecture": get_base_model_name(filename),
        }

    raise ValueError("Selectia de model nu este valida.")

def load_model_for_inference(architecture, num_classes, model_path):
    model_load_start = time.perf_counter()
    model = get_model(architecture, num_classes=num_classes, pretrained=False)

    if model is None:
        raise RuntimeError(f"get_model a returnat None pentru arhitectura '{architecture}'.")

    state = torch.load(model_path, map_location=DEVICE)
    if isinstance(state, dict) and "state_dict" in state:
        state = state["state_dict"]
    state = {k.replace("module.", "", 1): v for k, v in state.items()}
    model.load_state_dict(state)
    model = model.to(DEVICE)
    model.eval()
    model_load_time_ms = (time.perf_counter() - model_load_start) * 1000
    return model, model_load_time_ms

def run_multiclass_model(model, input_tensor):
    start_time = time.perf_counter()
    with torch.no_grad():
        outputs = model(input_tensor)
        probs = F.softmax(outputs, dim=1)[0]
        confidence, predicted_class = torch.max(probs, 0)
    inference_time_ms = (time.perf_counter() - start_time) * 1000
    return predicted_class.item(), confidence.item(), [float(p) for p in probs.cpu().numpy()], inference_time_ms

def run_binary_detector(model, input_tensor):
    start_time = time.perf_counter()
    with torch.no_grad():
        output = model(input_tensor).squeeze()
        disease_probability = torch.sigmoid(output).item()
    inference_time_ms = (time.perf_counter() - start_time) * 1000
    return float(disease_probability), inference_time_ms

@app.route('/api/models', methods=['GET'])
def get_models():
    groups, models = get_model_catalog()
    return jsonify({"groups": groups, "models": models})

@app.route('/api/predict', methods=['POST'])
def predict():
    if 'image' not in request.files or 'model_name' not in request.form:
        return jsonify({"error": "Imaginea si numele modelului sunt obligatorii."}), 400

    file = request.files['image']
    model_id = request.form['model_name']

    try:
        selection = resolve_model_selection(model_id)
        image = Image.open(file.stream).convert('RGB')
        original_image_size = image.size
        base_arch = selection["detector_arch"] if selection["mode"] == "pipeline" else selection["architecture"]
        input_size = get_input_size(base_arch)
        inference_image, preprocessing_info = preprocess_like_training_scripts(image, size=512)

        transform = transforms.Compose([
            transforms.Resize((input_size, input_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                 std=[0.229, 0.224, 0.225])
        ])
        input_tensor = transform(inference_image).unsqueeze(0).to(DEVICE)

        if selection["mode"] == "pipeline":
            detector, detector_load_time_ms = load_model_for_inference(
                selection["detector_arch"],
                num_classes=1,
                model_path=selection["detector_path"],
            )
            disease_probability, detector_time_ms = run_binary_detector(detector, input_tensor)
            healthy_probability = 1.0 - disease_probability
            model_load_time_ms = detector_load_time_ms
            inference_time_ms = detector_time_ms
            parameter_count, trainable_parameter_count = count_parameters(detector)

            stage2_used = False
            if disease_probability <= 0.5:
                predicted_class = 0
                confidence = healthy_probability
                raw_probabilities = [healthy_probability, disease_probability]
            elif selection["stage2_path"]:
                stage2_arch = selection["stage2_arch"]
                stage2_input_size = get_input_size(stage2_arch)
                if stage2_input_size != input_size:
                    stage2_transform = transforms.Compose([
                        transforms.Resize((stage2_input_size, stage2_input_size)),
                        transforms.ToTensor(),
                        transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                             std=[0.229, 0.224, 0.225])
                    ])
                    stage2_input_tensor = stage2_transform(inference_image).unsqueeze(0).to(DEVICE)
                else:
                    stage2_input_tensor = input_tensor

                stage2, stage2_load_time_ms = load_model_for_inference(
                    stage2_arch,
                    num_classes=4,
                    model_path=selection["stage2_path"],
                )
                stage2_class, stage2_confidence, stage2_probs, stage2_time_ms = run_multiclass_model(stage2, stage2_input_tensor)
                predicted_class = stage2_class + 1
                confidence = stage2_confidence
                raw_probabilities = [healthy_probability] + [disease_probability * prob for prob in stage2_probs]
                model_load_time_ms += stage2_load_time_ms
                inference_time_ms += stage2_time_ms
                stage2_used = True
            else:
                predicted_class = 1
                confidence = disease_probability
                raw_probabilities = [healthy_probability, disease_probability]

            model_display_name = selection["detector_name"]
            if selection["stage2_name"]:
                model_display_name = f"{selection['detector_name']} + {selection['stage2_name']}"
            pipeline_info = {
                "enabled": True,
                "detector_model": selection["detector_name"],
                "stage2_model": selection["stage2_name"],
                "stage2_used": stage2_used,
                "disease_probability": disease_probability,
            }
            model_path_for_size = selection["detector_path"]
        else:
            model, model_load_time_ms = load_model_for_inference(
                selection["architecture"],
                num_classes=5,
                model_path=selection["model_path"],
            )
            parameter_count, trainable_parameter_count = count_parameters(model)
            predicted_class, confidence, raw_probabilities, inference_time_ms = run_multiclass_model(model, input_tensor)
            model_display_name = selection["model_name"]
            pipeline_info = {"enabled": False}
            model_path_for_size = selection["model_path"]

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
                "model_name": model_display_name,
                "model_id": model_id,
                "mode": selection["mode"],
                "inference_time_ms": inference_time_ms,
                "model_load_time_ms": model_load_time_ms,
                "device": str(DEVICE),
                "cuda_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                "raw_probabilities": raw_probabilities,
                "input_size": input_size,
                "architecture": base_arch,
                "original_image_size": format_size(original_image_size),
                "inference_image_size": format_size(inference_image.size),
                "model_file_size_mb": os.path.getsize(model_path_for_size) / (1024 * 1024),
                "parameter_count": parameter_count,
                "trainable_parameter_count": trainable_parameter_count,
                "normalization": {
                    "mean": [0.485, 0.456, 0.406],
                    "std": [0.229, 0.224, 0.225],
                },
                "pipeline": pipeline_info,
            },
            "preprocessing": preprocessing_info,
            "processed_image": image_to_data_url(inference_image),
        }
        return jsonify(response)

    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
