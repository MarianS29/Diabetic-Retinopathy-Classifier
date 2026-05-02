import { useState, useEffect } from 'react';
import axios from 'axios';

const API_URL = 'http://127.0.0.1:5000/api';

function App() {
  const [models, setModels] = useState([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  // Incarcare lista de modele la pornire
  useEffect(() => {
    axios.get(`${API_URL}/models`)
      .then((res) => {
        setModels(res.data.models);
        if (res.data.models.length > 0) {
          setSelectedModel(res.data.models[0]);
        }
      })
      .catch((err) => setError('Eroare la încărcarea modelelor. Backend-ul este pornit?'));
  }, []);

  const handleImageChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      setImageFile(file);
      setPreview(URL.createObjectURL(file));
      setResult(null);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!imageFile || !selectedModel) {
      setError('Te rog selectează un model și o imagine.');
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
      <h1>Diabetic Retinopathy - Asistent Diagnostic</h1>
      
      {error && <div style={{ color: 'red', marginBottom: '1rem', padding: '1rem', background: '#fee' }}>{error}</div>}

      <div className="upload-section">
        <div className="form-group">
          <label><strong>Selectează Modelul (Din folderul de inferență):</strong></label>
          <select 
            value={selectedModel} 
            onChange={(e) => setSelectedModel(e.target.value)}
            style={{ padding: '0.5rem', fontSize: '1rem' }}
          >
            {models.map(model => (
              <option key={model} value={model}>{model}</option>
            ))}
          </select>
        </div>

        <div className="form-group">
          <label><strong>Încarcă Imagine Fund de Ochi:</strong></label>
          <input type="file" accept="image/*" onChange={handleImageChange} />
        </div>

        {preview && (
          <div style={{ textAlign: 'center' }}>
            <img src={preview} alt="Previzualizare" className="preview-image" />
          </div>
        )}

        <button onClick={handleSubmit} disabled={loading || !imageFile}>
          {loading ? 'Se procesează imaginea...' : 'Analizează Imaginea'}
        </button>
      </div>

      {result && (
        <div className="results-grid">
          <div className="card">
            <h3>Rezultat Diagnostic</h3>
            <p><strong>Stadiu detectat:</strong> <span style={{ fontSize: '1.2rem', color: '#e74c3c' }}>{result.stage_name} (Clasa {result.stage})</span></p>
            <p><strong>Nivel de Încredere (Confidence):</strong> {(result.confidence * 100).toFixed(2)}%</p>
            
            <hr style={{ margin: '1.5rem 0', border: 'none', borderTop: '1px solid #eee' }}/>
            
            <h4>Recomandări pentru Medic</h4>
            <p>{result.recommendations.doctor}</p>
            
            <h4>Recomandări pentru Pacient</h4>
            <p>{result.recommendations.patient}</p>
          </div>

          <div className="card">
            <h3>Date pentru Ingineri (Metadate Model)</h3>
            <div className="engineering-data">
              <p>Fișier model: {result.model_data.model_name}</p>
              <p>Timp Inferență: {result.model_data.inference_time_ms.toFixed(2)} ms</p>
              <p>Dispozitiv utilizat: {result.model_data.device}</p>
              <p>Extragere features: Reușită</p>
              <br/>
              <p>Probabilități Raw (Softmax):</p>
              <ul>
                {result.model_data.raw_probabilities.map((prob, idx) => (
                  <li key={idx}>Clasa {idx}: {(prob * 100).toFixed(2)}%</li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;