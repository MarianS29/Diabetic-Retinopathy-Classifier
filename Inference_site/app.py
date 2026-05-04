import os
import sys
import time
import torch
import torch.nn.functional as F
from torchvision import transforms
from PIL import Image
from flask import Flask, request, jsonify
from flask_cors import CORS

# Adăugăm calea către notebook-uri pentru a putea importa get_model din builder.py
BASE_DIR = r"B:\Projects\Disertatie\Diabetic-Retinopathy-Classifier"
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
        "name": "Fără Retinopatie (No DR)",
        "patient": "Mențineți un stil de viață sănătos și veniți la un control de rutină o dată pe an.",
        "doctor": "Nu se observă anomalii pe fundul de ochi. Programare pentru control anual."
    },
    1: {
        "name": "Retinopatie Ușoară (Mild)",
        "patient": "Este necesar controlul strict al glicemiei și dietei. Reveniți la control în 6-12 luni.",
        "doctor": "Prezența microanevrismelor. Nu necesită tratament oftalmologic imediat, doar optimizare metabolică."
    },
    2: {
        "name": "Retinopatie Moderată (Moderate)",
        "patient": "Sunt necesare controale oftalmologice mai dese (la 3-6 luni) și analize detaliate.",
        "doctor": "Se recomandă evaluare atentă pentru identificarea unui potențial edem macular clinic semnificativ."
    },
    3: {
        "name": "Retinopatie Severă (Severe)",
        "patient": "Stare avansată. Trebuie să urmați tratamentul cu strictețe și să efectuați analize de urgență.",
        "doctor": "Risc crescut de progresie către faza proliferativă. Recomandată Angiofluorografie și monitorizare strânsă."
    },
    4: {
        "name": "Retinopatie Proliferativă (Proliferative)",
        "patient": "Situație critică pentru vedere. Poate fi necesară intervenție cu laser sau operație. Prezentați-vă urgent la specialist.",
        "doctor": "Se impune fotocoagulare panretiniană (PRP) sau intervenție chirurgicală. Trimitere urgentă la specialist retinolog."
    }
}

def get_base_model_name(filename):
    # Extrage tipul de retea din numele modelului salvat (ex: 'best_resnet50_ce_adam_LR_0.0001.pth' -> 'resnet50')
    name = filename.lower()
    if 'resnet50' in name: return 'resnet50'
    if 'efficientnet_b3' in name: return 'efficientnet_b3'
    if 'efficientnet_b0' in name: return 'efficientnet_b0'
    if 'densenet121' in name: return 'densenet121'
    if 'inception_v3' in name: return 'inception_v3'
    if 'incres_v2' in name: return 'incres_v2'
    return 'resnet50' # Default fallback

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
        # Preprocesare imagine
        image = Image.open(file.stream).convert('RGB')
        transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                 std=[0.229, 0.224, 0.225])
        ])
        input_tensor = transform(image).unsqueeze(0).to(DEVICE)

        # Încarcă modelul potrivit
        base_arch = get_base_model_name(model_name)
        model = get_model(base_arch, num_classes=5, pretrained=False)
        model.load_state_dict(torch.load(model_path, map_location=DEVICE))
        model = model.to(DEVICE)
        model.eval()

        # Evaluare și timing
        start_time = time.perf_counter()
        with torch.no_grad():
            outputs = model(input_tensor)
            probs = F.softmax(outputs, dim=1)[0]
            confidence, predicted_class = torch.max(probs, 0)
        end_time = time.perf_counter()

        predicted_class = predicted_class.item()
        confidence = confidence.item()
        inference_time_ms = (end_time - start_time) * 1000

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
                "device": str(DEVICE),
                "raw_probabilities": [float(p) for p in probs.cpu().numpy()]
            }
        }
        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True, use_reloader=False)
