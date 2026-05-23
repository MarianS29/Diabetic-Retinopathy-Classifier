import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import {
  Activity,
  AlertCircle,
  CheckCircle,
  FileText,
  Image as ImageIcon,
  Moon,
  Rotate3D,
  Stethoscope,
  Sun,
  UploadCloud,
  X,
} from 'lucide-react';

const API_URL = 'http://127.0.0.1:5000/api';

function EyeModel3D({ imageUrl }) {
  const mountRef = useRef(null);

  useEffect(() => {
    if (!mountRef.current || !imageUrl) return undefined;

    const mount = mountRef.current;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    camera.position.set(0, 0, 3.2);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.enablePan = false;
    controls.minDistance = 2.15;
    controls.maxDistance = 5;
    controls.rotateSpeed = 0.75;
    controls.zoomSpeed = 0.75;

    const texture = new THREE.TextureLoader().load(imageUrl);
    texture.colorSpace = THREE.SRGBColorSpace;

    const retina = new THREE.Mesh(
      new THREE.SphereGeometry(1, 96, 96),
      new THREE.MeshStandardMaterial({
        map: texture,
        roughness: 0.82,
        metalness: 0.02,
      }),
    );
    retina.rotation.y = -0.35;
    scene.add(retina);

    const glow = new THREE.Mesh(
      new THREE.SphereGeometry(1.015, 96, 96),
      new THREE.MeshBasicMaterial({
        color: 0x8fb6ff,
        transparent: true,
        opacity: 0.08,
      }),
    );
    scene.add(glow);

    scene.add(new THREE.AmbientLight(0xffffff, 0.9));
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.45);
    keyLight.position.set(1.8, 2.2, 3);
    scene.add(keyLight);

    let frameId = null;
    const resize = () => {
      const { clientWidth, clientHeight } = mount;
      const width = Math.max(clientWidth, 240);
      const height = Math.max(clientHeight, 260);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };

    const animate = () => {
      controls.update();
      glow.rotation.y -= 0.002;
      renderer.render(scene, camera);
      frameId = requestAnimationFrame(animate);
    };

    resize();
    animate();
    window.addEventListener('resize', resize);

    return () => {
      window.removeEventListener('resize', resize);
      if (frameId) cancelAnimationFrame(frameId);
      texture.dispose();
      retina.geometry.dispose();
      retina.material.dispose();
      glow.geometry.dispose();
      glow.material.dispose();
      controls.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, [imageUrl]);

  return <div ref={mountRef} className="eye-3d-canvas" aria-label="Vizualizare 3D imagine retina" />;
}

function App() {
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [theme, setTheme] = useState(() => localStorage.getItem('dr-theme') || 'light');

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('dr-theme', theme);
  }, [theme]);

  useEffect(() => {
    axios.get(`${API_URL}/models`)
      .then((res) => {
        setModels(res.data.models);
        if (res.data.models.length > 0) setSelectedModel(res.data.models[0]);
      })
      .catch(() => setError('Eroare la conectarea cu serverul. Asigura-te ca backend-ul este pornit.'));
  }, []);

  const resetImage = () => {
    if (preview) URL.revokeObjectURL(preview);
    setPreview(null);
    setImageFile(null);
    setResult(null);
  };

  const handleImageChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (preview) URL.revokeObjectURL(preview);
    setImageFile(file);
    setPreview(URL.createObjectURL(file));
    setResult(null);
    setError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!imageFile || !selectedModel) {
      setError('Te rog selecteaza un model si incarca o imagine.');
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    const formData = new FormData();
    formData.append('image', imageFile);
    formData.append('model_name', selectedModel);

    try {
      const response = await axios.post(`${API_URL}/predict`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setResult(response.data);
    } catch (err) {
      setError(err.response?.data?.error || 'A aparut o eroare la procesarea imaginii.');
    } finally {
      setLoading(false);
    }
  };

  const eye3dImage = preview;
  const probabilities = result?.model_data?.raw_probabilities || [];
  const sortedProbabilities = probabilities
    .map((prob, idx) => ({ prob, idx }))
    .sort((a, b) => b.prob - a.prob);
  const secondChoice = sortedProbabilities[1];

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <span className="brand-mark"><Activity size={20} /></span>
          <div>
            <h1>Diabetic Retinopathy</h1>
            <p>Asistent inteligent pentru clasificarea imaginilor fundus</p>
          </div>
        </div>
        <button
          type="button"
          className="theme-toggle"
          onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
          aria-label="Schimba tema"
        >
          {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
          <span>{theme === 'light' ? 'Dark' : 'Light'}</span>
        </button>
      </header>

      {error && (
        <div className="error-message">
          <AlertCircle size={20} />
          <span>{error}</span>
        </div>
      )}

      <main className="main-grid">
        <section className="panel input-panel">
          <div className="panel-header">
            <h2><ImageIcon size={20} /> Imagine si model</h2>
          </div>

          <div className="form-group">
            <label htmlFor="model-select">Model de inferenta</label>
            <select
              id="model-select"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
            >
              {models.length === 0 ? <option>Se incarca modelele...</option> : null}
              {models.map((model) => (
                <option key={model} value={model}>{model}</option>
              ))}
            </select>
          </div>

          <div className="form-group centered-group">
            <label>Imagine fund de ochi</label>
            {!preview ? (
              <div className="upload-area">
                <input type="file" accept="image/*" onChange={handleImageChange} />
                <UploadCloud className="upload-icon" />
                <div className="upload-text">Apasa sau trage imaginea aici</div>
                <div className="upload-hint">JPG, PNG, JPEG</div>
              </div>
            ) : (
              <div className="preview-container">
                <img src={preview} alt="Previzualizare" className="preview-image" />
                <button className="close-btn" onClick={resetImage} title="Schimba imaginea" type="button">
                  <X size={18} />
                </button>
              </div>
            )}
          </div>

          <button className="button-primary" onClick={handleSubmit} disabled={loading || !imageFile} type="button">
            {loading ? <><span className="spinner" /> Se analizeaza...</> : 'Analizeaza imaginea'}
          </button>
        </section>

        <section className="panel eye-panel">
          <div className="panel-header">
            <h2><Rotate3D size={20} /> Vizualizare 3D</h2>
          </div>
          {eye3dImage ? (
            <>
              <EyeModel3D imageUrl={eye3dImage} />
              <div className="preprocess-status">
                <span>Proiectie din imaginea originala</span>
                <strong>Trage cu mouse-ul pentru rotire, scroll pentru zoom</strong>
              </div>
            </>
          ) : (
            <div className="empty-3d">
              <Rotate3D size={36} />
              <span>Incarca o imagine pentru a vedea retina in 3D</span>
            </div>
          )}
        </section>
      </main>

      {result && (
        <section className="results-section">
          <div className="results-grid">
            <article className="result-card">
              <h3><Activity size={20} /> Rezultat</h3>
              <div className="diagnostic-row">
                <span>Stadiu detectat</span>
                <strong>Clasa {result.stage}</strong>
              </div>
              <div className="stage-badge">{result.stage_name}</div>
              <div className="confidence-row">
                <span>Nivel de incredere</span>
                <strong>{(result.confidence * 100).toFixed(1)}%</strong>
              </div>
              <div className="confidence-bar-bg">
                <div className="confidence-bar-fill" style={{ width: `${result.confidence * 100}%` }} />
              </div>
              {secondChoice ? (
                <div className="result-extra">
                  <p><span>A doua optiune</span><strong>Clasa {secondChoice.idx} ({(secondChoice.prob * 100).toFixed(1)}%)</strong></p>
                  <p><span>Separare top-2</span><strong>{((result.confidence - secondChoice.prob) * 100).toFixed(1)} pp</strong></p>
                </div>
              ) : null}
            </article>

            <article className="result-card">
              <h3><Stethoscope size={20} /> Recomandari</h3>
              <div className="recommendation">
                <h4>Medic</h4>
                <p>{result.recommendations.doctor}</p>
                <h4>Pacient</h4>
                <p>{result.recommendations.patient}</p>
                <h4>Observatie tehnica</h4>
                <p>
                  {result.preprocessing?.applied
                    ? 'Imaginea a fost detectata ca neprelucrata si a trecut prin crop, resize si normalizare inainte de predictie.'
                    : 'Imaginea pare deja preprocesata; pentru inferenta s-a aplicat doar redimensionarea si normalizarea ceruta de model.'}
                </p>
              </div>
            </article>

            <article className="result-card">
              <h3><FileText size={20} /> Metadate model</h3>
              <div className="engineering-data">
                <p><span>Fisier</span><strong>{result.model_data.model_name}</strong></p>
                <p><span>Arhitectura</span><strong>{result.model_data.architecture || 'n/a'}</strong></p>
                <p><span>Input</span><strong>{result.model_data.input_size ? `${result.model_data.input_size} px` : 'n/a'}</strong></p>
                <p><span>Imagine originala</span><strong>{result.model_data.original_image_size || 'n/a'}</strong></p>
                <p><span>Imagine inferenta</span><strong>{result.model_data.inference_image_size || 'n/a'}</strong></p>
                <p><span>Timp executie</span><strong>{result.model_data.inference_time_ms.toFixed(2)} ms</strong></p>
                <p><span>Incarcare model</span><strong>{result.model_data.model_load_time_ms?.toFixed(2) || 'n/a'} ms</strong></p>
                <p><span>Dispozitiv</span><strong>{result.model_data.device}</strong></p>
                <p><span>CUDA</span><strong>{result.model_data.cuda_name || 'n/a'}</strong></p>
                <p><span>Parametri</span><strong>{result.model_data.parameter_count?.toLocaleString('ro-RO') || 'n/a'}</strong></p>
                <p><span>Parametri antrenabili</span><strong>{result.model_data.trainable_parameter_count?.toLocaleString('ro-RO') || 'n/a'}</strong></p>
                <p><span>Dimensiune model</span><strong>{result.model_data.model_file_size_mb?.toFixed(2) || 'n/a'} MB</strong></p>
                <p><span>Margin top-2</span><strong>{result.model_data.top2_margin != null ? `${(result.model_data.top2_margin * 100).toFixed(2)} pp` : 'n/a'}</strong></p>
                <p><span>Preprocesare</span><strong>{result.preprocessing?.applied ? 'aplicata' : 'neaplicata'}</strong></p>
                <p><span>Dark ratio</span><strong>{result.preprocessing ? (result.preprocessing.dark_ratio * 100).toFixed(2) : 'n/a'}%</strong></p>
                <p><span>Dark border</span><strong>{result.preprocessing ? (result.preprocessing.dark_border_ratio * 100).toFixed(2) : 'n/a'}%</strong></p>
                <p><span>Aspect delta</span><strong>{result.preprocessing ? result.preprocessing.aspect_delta.toFixed(3) : 'n/a'}</strong></p>
                <p><span>Normalizare</span><strong>ImageNet mean/std</strong></p>
                <p>
                  <span>Features</span>
                  <strong className="status-ok"><CheckCircle size={16} /> Reusita</strong>
                </p>
                <div className="probability-title">Probabilitati softmax</div>
                <ul>
                  {result.model_data.raw_probabilities.map((prob, idx) => (
                    <li key={idx}>
                      <span>Clasa {idx}</span>
                      <strong>{(prob * 100).toFixed(2)}%</strong>
                    </li>
                  ))}
                </ul>
              </div>
            </article>
          </div>
        </section>
      )}
    </div>
  );
}

export default App;
