import { useState, useEffect } from 'react';
import axios from 'axios';
import { UploadCloud, AlertCircle, Activity, FileText, CheckCircle, X } from 'lucide-react';

const API_URL = 'http://127.0.0.1:5000/api';

function App() {
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  // Încărcare listă de modele la pornire
  useEffect(() => {
    axios.get(`${API_URL}/models`)
      .then((res) => {
        setModels(res.data.models);
        if (res.data.models.length > 0) {
          setSelectedModel(res.data.models[0]);
        }
      })
      .catch((err) => setError('Eroare la conectarea cu serverul. Asigură-te că backend-ul este pornit.'));
  }, []);

  const handleImageChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      setImageFile(file);
      setPreview(URL.createObjectURL(file));
      setResult(null);
      setError('');
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!imageFile || !selectedModel) {
      setError('Te rog selectează un model și încarcă o imagine.');
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
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      setResult(response.data);
    } catch (err) {
      setError(err.response?.data?.error || 'A apărut o eroare la procesarea imaginii.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="container">
      <div className="header">
        <h1>Diabetic Retinopathy</h1>
        <p>Asistent inteligent pentru diagnosticul retinopatiei diabetice</p>
      </div>
      
      {error && (
        <div className="error-message">
          <AlertCircle size={20} />
          <span>{error}</span>
        </div>
      )}

      <div className="card">
        <div className="form-group">
          <label>Model de Inferență</label>
          <select 
            value={selectedModel} 
            onChange={(e) => setSelectedModel(e.target.value)}
          >
            {models.length === 0 ? <option>Se încarcă modelele...</option> : null}
            {models.map(model => (
              <option key={model} value={model}>{model}</option>
            ))}
          </select>
        </div>

        <div className="form-group">
          <label>Imagine Fund de Ochi</label>
          {!preview ? (
            <div className="upload-area">
              <input type="file" accept="image/*" onChange={handleImageChange} />
              <UploadCloud className="upload-icon" />
              <div className="upload-text">Apasă sau trage imaginea aici</div>
              <div className="upload-hint">Format acceptat: JPG, PNG, JPEG</div>
            </div>
          ) : (
            <div className="preview-container">
              <img src={preview} alt="Previzualizare" className="preview-image" />
              <button 
                className="close-btn"
                onClick={() => { setPreview(null); setImageFile(null); setResult(null); }}
                title="Schimbă imaginea"
              >
                <X size={18} />
              </button>
            </div>
          )}
        </div>

        <button 
          className="button-primary"
          onClick={handleSubmit} 
          disabled={loading || !imageFile}
        >
          {loading ? (
            <><span className="spinner"></span> Se analizează...</>
          ) : (
            'Analizează Imaginea'
          )}
        </button>
      </div>

      {result && (
        <div className="results-section">
          <div className="results-grid">
            <div className="result-card">
              <h3><Activity size={20} strokeWidth={1.5} /> Rezultat Diagnostic</h3>
              
              <div style={{ marginBottom: '2rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <span style={{ fontWeight: 500, color: 'var(--text-secondary)' }}>Stadiu Detectat</span>
                  <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Clasa {result.stage}</span>
                </div>
                <div className="stage-badge">
                  {result.stage_name}
                </div>
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>
                  <span>Nivel de încredere</span>
                  <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{(result.confidence * 100).toFixed(1)}%</span>
                </div>
                <div className="confidence-bar-bg">
                  <div 
                    className="confidence-bar-fill" 
                    style={{ width: `${result.confidence * 100}%` }}
                  ></div>
                </div>
              </div>
              
              <div className="divider"></div>
              
              <div className="recommendation">
                <h4>Recomandări Medic</h4>
                <p>{result.recommendations.doctor}</p>
                
                <h4>Recomandări Pacient</h4>
                <p>{result.recommendations.patient}</p>
              </div>
            </div>

            <div className="result-card">
              <h3><FileText size={20} strokeWidth={1.5} /> Metadate Model</h3>
              <div className="engineering-data">
                <p>
                  <span>Fișier</span>
                  <strong>{result.model_data.model_name}</strong>
                </p>
                <p>
                  <span>Timp Execuție</span>
                  <strong>{result.model_data.inference_time_ms.toFixed(2)} ms</strong>
                </p>
                <p>
                  <span>Dispozitiv</span>
                  <strong>{result.model_data.device}</strong>
                </p>
                <p>
                  <span>Extragere Features</span>
                  <strong style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <CheckCircle size={16} color="var(--text-primary)" strokeWidth={1.5} /> Reușită
                  </strong>
                </p>
                
                <div style={{ marginTop: '1.5rem', marginBottom: '0.75rem', fontWeight: 500, color: 'var(--text-primary)' }}>
                  Probabilități (Softmax)
                </div>
                <ul>
                  {result.model_data.raw_probabilities.map((prob, idx) => (
                    <li key={idx}>
                      <span>Clasa {idx}</span>
                      <strong>{(prob * 100).toFixed(2)}%</strong>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;