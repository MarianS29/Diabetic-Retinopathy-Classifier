import { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import {
  Activity,
  AlertCircle,
  FileText,
  Image as ImageIcon,
  Moon,
  ScanEye,
  Stethoscope,
  Sun,
  UploadCloud,
  X,
} from 'lucide-react';

const API_URL = 'http://127.0.0.1:5000/api';

function ProcessedImageViewer({ imageUrl }) {
  const viewerRef = useRef(null);
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 });
  const [drag, setDrag] = useState(null);

  const resetView = () => {
    setView({ scale: 1, x: 0, y: 0 });
  };

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !imageUrl) return undefined;

    const handleWheel = (event) => {
      event.preventDefault();
      event.stopPropagation();

      const rect = viewer.getBoundingClientRect();
      const pointerX = event.clientX - rect.left - rect.width / 2;
      const pointerY = event.clientY - rect.top - rect.height / 2;
      const zoomFactor = event.deltaY < 0 ? 1.18 : 0.84;

      setView((current) => {
        const nextScale = Math.min(8, Math.max(1, current.scale * zoomFactor));
        const ratio = nextScale / current.scale;
        return {
          scale: nextScale,
          x: pointerX - (pointerX - current.x) * ratio,
          y: pointerY - (pointerY - current.y) * ratio,
        };
      });
    };

    viewer.addEventListener('wheel', handleWheel, { passive: false });
    return () => viewer.removeEventListener('wheel', handleWheel);
  }, [imageUrl]);

  const handlePointerDown = (event) => {
    if (!imageUrl) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrag({
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      viewX: view.x,
      viewY: view.y,
    });
  };

  const handlePointerMove = (event) => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    setView((current) => ({
      ...current,
      x: drag.viewX + event.clientX - drag.startX,
      y: drag.viewY + event.clientY - drag.startY,
    }));
  };

  const handlePointerUp = () => {
    setDrag(null);
  };

  if (!imageUrl) {
    return (
      <div className="processed-placeholder">
        <ScanEye size={36} />
      </div>
    );
  }

  return (
    <div
      ref={viewerRef}
      className="processed-viewer"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      onDoubleClick={resetView}
      role="img"
      aria-label="Imagine preprocesata"
    >
      <img
        src={imageUrl}
        alt="Imagine preprocesata"
        draggable="false"
        style={{
          transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
        }}
      />
      <div className="zoom-badge">{view.scale.toFixed(1)}x</div>
    </div>
  );
}

function App() {
  const [models, setModels] = useState([]);
  const [modelGroups, setModelGroups] = useState([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [imagePreprocessed, setImagePreprocessed] = useState(true);
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
        const nextModels = res.data.models || [];
        setModels(nextModels);
        setModelGroups(res.data.groups || []);
        const firstAvailable = nextModels.find((model) => model.available !== false);
        if (firstAvailable) setSelectedModel(firstAvailable.id);
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
    formData.append('image_preprocessed', imagePreprocessed ? 'true' : 'false');

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

  const processedPreview = result?.processed_image;
  const probabilities = result?.model_data?.raw_probabilities || [];
  const probabilityKind = result?.model_data?.pipeline?.stage2_details?.probability_kind;
  const hasConfidence = typeof result?.confidence === 'number';
  const hasClassProbabilities = probabilities.length >= 5 || probabilityKind === 'softmax';
  const probabilityTitle = result?.model_data?.pipeline?.enabled
    ? (probabilityKind === 'softmax' ? 'Probabilitati softmax pipeline' : 'Probabilitate detector binar')
    : 'Probabilitati softmax';
  const pipelineStage2Used = result?.model_data?.pipeline?.enabled && result.model_data.pipeline.stage2_used;
  const classProbabilityRows = probabilities
    .map((prob, idx) => ({ prob, idx }))
    .filter(({ idx }) => !pipelineStage2Used || idx > 0);
  const sortedProbabilities = [...classProbabilityRows]
    .sort((a, b) => b.prob - a.prob);
  const predictedProbability = classProbabilityRows.find(({ idx }) => idx === result?.stage);
  const secondChoice = hasClassProbabilities
    ? sortedProbabilities.find(({ idx }) => idx !== result?.stage) || null
    : null;
  const regressionAlternativeClass = result?.model_data?.pipeline?.stage2_details?.alternative_class_1_4;
  const mainGradeProbabilities = result?.model_data?.pipeline?.stage2_details?.grade_probabilities_1_4 || [];
  const stage2PredictedGrade = result?.model_data?.pipeline?.stage2_details?.stage2_predicted_grade;
  const showMainGradeProbabilities = result?.model_data?.model_id === 'main:pipeline'
    && result?.model_data?.pipeline?.stage2_evaluated
    && mainGradeProbabilities.length > 0;
  const renderProbabilityBlocks = (probability) => {
    const filled = Math.max(0, Math.min(20, Math.round(probability * 20)));
    return `${'█'.repeat(filled)}${'░'.repeat(20 - filled)}`;
  };
  const groupedModels = modelGroups
    .map((group) => ({
      ...group,
      models: models.filter((model) => model.group === group.id),
    }))
    .filter((group) => group.models.length > 0);
  const ungroupedModels = models.filter((model) => !modelGroups.some((group) => group.id === model.group));

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
              {groupedModels.map((group) => (
                <optgroup key={group.id} label={group.label}>
                  {group.models.map((model) => (
                    <option key={model.id} value={model.id} disabled={model.available === false}>
                      {model.label}
                    </option>
                  ))}
                </optgroup>
              ))}
              {ungroupedModels.map((model) => (
                <option key={model.id} value={model.id} disabled={model.available === false}>
                  {model.label}
                </option>
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

          <label className="switch-row">
            <input
              type="checkbox"
              checked={imagePreprocessed}
              onChange={(e) => setImagePreprocessed(e.target.checked)}
            />
            <span className="switch-track" aria-hidden="true">
              <span className="switch-thumb" />
            </span>
            <span>Imagine deja preprocesata</span>
          </label>

          <button className="button-primary" onClick={handleSubmit} disabled={loading || !imageFile} type="button">
            {loading ? <><span className="spinner" /> Se analizeaza...</> : 'Analizeaza imaginea'}
          </button>
        </section>

        <section className="panel processing-panel">
          {preview ? (
            <div className="processing-viewer-shell">
              <ProcessedImageViewer imageUrl={processedPreview} />
            </div>
          ) : (
            <div className="empty-processing">
              <ScanEye size={36} />
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
                <span>{hasConfidence ? 'Nivel de incredere' : 'Scor regresie'}</span>
                <strong>
                  {hasConfidence
                    ? `${(result.confidence * 100).toFixed(1)}%`
                    : result.model_data.pipeline?.stage2_details?.regression_score?.toFixed(3) || 'n/a'}
                </strong>
              </div>
              {hasConfidence ? (
                <div className="confidence-bar-bg">
                  <div className="confidence-bar-fill" style={{ width: `${result.confidence * 100}%` }} />
                </div>
              ) : null}
              {showMainGradeProbabilities ? (
                <div className="grade-probabilities">
                  {mainGradeProbabilities.map(({ grade, probability }) => (
                    <div className="grade-probability-row" key={grade}>
                      <div className="grade-probability-label">
                        <span>Gradul {grade}</span>
                        <span className="grade-probability-blocks">{renderProbabilityBlocks(probability)}</span>
                        <strong>{Math.round(probability * 100)}%</strong>
                        {stage2PredictedGrade === grade ? <em>◄ predictie</em> : null}
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
              {secondChoice ? (
                <div className="result-extra">
                  <p><span>A doua optiune</span><strong>Clasa {secondChoice.idx} ({(secondChoice.prob * 100).toFixed(1)}%)</strong></p>
                  {predictedProbability ? (
                    <p><span>Separare top-2</span><strong>{((predictedProbability.prob - secondChoice.prob) * 100).toFixed(1)} pp</strong></p>
                  ) : null}
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
                    ? 'Imaginea a fost preprocesata inainte de inferenta.'
                    : 'Imaginea a fost trimisa catre model fara preprocesare suplimentara.'}
                </p>
              </div>
            </article>

            <article className="result-card">
              <h3><FileText size={20} /> Metadate model</h3>
              <div className="engineering-data">
                <div className="probability-title">
                  {probabilityTitle}
                </div>
                <ul>
                  {classProbabilityRows.map(({ prob, idx }) => (
                    <li key={idx}>
                      <span>{result.model_data.pipeline?.enabled && idx === 1 && result.model_data.raw_probabilities.length === 2 ? 'Prob. boala' : `Clasa ${idx}`}</span>
                      <strong>{(prob * 100).toFixed(2)}%</strong>
                    </li>
                  ))}
                </ul>
                {pipelineStage2Used && secondChoice ? (
                  <p><span>Urmatoarea clasa 1-4</span><strong>Clasa {secondChoice.idx} ({(secondChoice.prob * 100).toFixed(2)}%)</strong></p>
                ) : null}
                {pipelineStage2Used && !secondChoice && regressionAlternativeClass ? (
                  <p><span>Urmatoarea clasa 1-4</span><strong>Clasa {regressionAlternativeClass} (dupa scor regresie)</strong></p>
                ) : null}
                <p><span>Fisier</span><strong>{result.model_data.model_name}</strong></p>
                <p><span>Arhitectura</span><strong>{result.model_data.architecture || 'n/a'}</strong></p>
                <p><span>Input</span><strong>{result.model_data.input_size ? `${result.model_data.input_size} px` : 'n/a'}</strong></p>
                <p><span>Imagine originala</span><strong>{result.model_data.original_image_size || 'n/a'}</strong></p>
                <p><span>Imagine inferenta</span><strong>{result.model_data.inference_image_size || 'n/a'}</strong></p>
                <p><span>Timp executie</span><strong>{result.model_data.inference_time_ms.toFixed(2)} ms</strong></p>
                <p><span>Metoda</span><strong>{result.preprocessing?.method || 'n/a'}</strong></p>
                {result.model_data.pipeline?.enabled ? (
                  <>
                    <p><span>Detector</span><strong>{result.model_data.pipeline.detector_model}</strong></p>
                    <p><span>Clasificator 1-4</span><strong>{result.model_data.pipeline.stage2_model || 'indisponibil'}</strong></p>
                    <p><span>Ramura</span><strong>{result.model_data.pipeline.stage2_mode || 'n/a'}</strong></p>
                    {result.model_data.pipeline.stage2_details?.regression_score !== undefined ? (
                      <p><span>Scor regresie</span><strong>{result.model_data.pipeline.stage2_details.regression_score.toFixed(3)}</strong></p>
                    ) : null}
                  </>
                ) : null}
              </div>
            </article>
          </div>
        </section>
      )}
    </div>
  );
}

export default App;
