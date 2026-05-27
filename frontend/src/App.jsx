import { useState, useRef, useCallback, useEffect } from 'react'

// API base URL: in production uses Render directly (set VITE_API_URL in Vercel env)
// In dev: uses /api which Vite proxy forwards to localhost:8000
const API_BASE = import.meta.env.VITE_API_URL || '/api'
import './App.css'
import {
  LogoPCB, IconUpload, IconScan, IconChart, IconMapPin,
  IconSun, IconMoon, IconX, IconAlert, IconImage,
  IconTarget, IconLayers, IconDownload, IconHistory,
  IconServer, IconWifiOff, IconFile, IconCheck, IconZap
} from './icons'

// ── Constants ────────────────────────────────────────────────────────────────
const CLASS_COLORS = {
  Missing_hole    : '#ef4444',
  Mouse_bite      : '#f97316',
  Open_circuit    : '#eab308',
  Short           : '#7c3aed',
  Spur            : '#22c55e',
  Spurious_copper : '#06b6d4',
}

const MODEL_STATS = [
  { label: 'Architecture', value: 'EfficientNet-B0' },
  { label: 'Val Accuracy',  value: '99.1%'          },
  { label: 'Defect Classes',value: '6'              },
  { label: 'Training Crops',value: '2,922'          },
  { label: 'Dataset',       value: 'DeepPCB'        },
]

// ── Image Compression ─────────────────────────────────────────────────────────
// If file > 5MB, scale it down and convert to JPEG before sending to API.
// This keeps upload fast without losing the defect details (PCB images are huge).
async function compressImage(file, maxMB = 5) {
  if (file.size <= maxMB * 1024 * 1024) return file
  return new Promise((resolve) => {
    const img = new Image()
    img.src = URL.createObjectURL(file)
    img.onload = () => {
      const ratio  = Math.sqrt((maxMB * 1024 * 1024) / file.size)
      const canvas = document.createElement('canvas')
      canvas.width  = Math.round(img.width  * ratio)
      canvas.height = Math.round(img.height * ratio)
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height)
      canvas.toBlob(
        (blob) => resolve(new File([blob], file.name, { type: 'image/jpeg' })),
        'image/jpeg', 0.88
      )
    }
  })
}

// ── Format file size ──────────────────────────────────────────────────────────
function formatBytes(bytes) {
  if (bytes < 1024)        return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ── Sub-Components ────────────────────────────────────────────────────────────
function ConfidenceBar({ name, value, isTop }) {
  const color = CLASS_COLORS[name] || '#7c3aed'
  return (
    <div className="prob-row">
      <div className="prob-header">
        <span className="prob-name" style={isTop ? { color: 'var(--text-primary)', fontWeight: 600 } : {}}>
          {name.replace(/_/g, ' ')}
        </span>
        <span className="prob-value" style={{ color: isTop ? color : 'var(--text-secondary)' }}>
          {value.toFixed(1)}%
        </span>
      </div>
      <div className="prob-bar-bg">
        <div className="prob-bar-fill"
          style={{ width: `${value}%`, background: isTop ? color : 'var(--border-hover)' }} />
      </div>
    </div>
  )
}

function RegionCard({ region, index }) {
  const color = CLASS_COLORS[region.class] || '#7c3aed'
  const [x1, y1, x2, y2] = region.bbox
  return (
    <div className="region-card" style={{ borderLeftColor: color }}>
      <div className="region-header">
        <span className="region-num">Region {index + 1}</span>
        <span className="region-cls" style={{ color }}>{region.class.replace(/_/g, ' ')}</span>
        <span className="region-conf">{region.confidence}%</span>
      </div>
      <div className="region-bbox">({x1}, {y1}) &rarr; ({x2}, {y2})</div>
    </div>
  )
}

// ── Skeleton ──────────────────────────────────────────────────────────────────
function SkeletonResults() {
  return (
    <div className="skeleton-wrap">
      <div className="skeleton sk-verdict" />
      <div className="skeleton sk-label" />
      <div className="skeleton sk-bar" />
      <div className="skeleton sk-bar-sm" />
      <div className="skeleton sk-bar-xs" />
      <div className="skeleton sk-bar" />
      <div className="skeleton sk-bar-sm" />
      <div className="skeleton sk-bar-xs" />
    </div>
  )
}

// ── Canvas Draw ───────────────────────────────────────────────────────────────
function drawCanvas(canvas, imageUrl, regions) {
  if (!canvas || !imageUrl) return
  const ctx = canvas.getContext('2d')
  const img = new Image()
  img.src   = imageUrl
  img.onload = () => {
    const displayW = canvas.offsetWidth || 600
    const scale    = displayW / img.naturalWidth
    canvas.width   = displayW
    canvas.height  = img.naturalHeight * scale
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
    if (!regions || regions.length === 0) return

    regions.forEach((region, idx) => {
      const [x1, y1, x2, y2] = region.bbox
      const color = CLASS_COLORS[region.class] || '#7c3aed'
      const sx = x1*scale, sy = y1*scale, sw = (x2-x1)*scale, sh = (y2-y1)*scale

      ctx.shadowColor = color; ctx.shadowBlur = 14
      ctx.strokeStyle = color; ctx.lineWidth = Math.max(2, 2.5*scale)
      ctx.strokeRect(sx, sy, sw, sh)
      ctx.shadowBlur = 0
      ctx.fillStyle  = color + '1a'; ctx.fillRect(sx, sy, sw, sh)

      const cs = Math.min(sw, sh, 14)
      ctx.strokeStyle = color; ctx.lineWidth = Math.max(2, 3.5*scale)
      ;[
        [[sx,sy+cs],[sx,sy],[sx+cs,sy]],
        [[sx+sw-cs,sy],[sx+sw,sy],[sx+sw,sy+cs]],
        [[sx,sy+sh-cs],[sx,sy+sh],[sx+cs,sy+sh]],
        [[sx+sw-cs,sy+sh],[sx+sw,sy+sh],[sx+sw,sy+sh-cs]]
      ].forEach(pts => {
        ctx.beginPath(); ctx.moveTo(...pts[0]); ctx.lineTo(...pts[1]); ctx.lineTo(...pts[2]); ctx.stroke()
      })

      const label = `${idx+1}  ${region.class.replace(/_/g,' ')}  ${region.confidence}%`
      const fs = Math.max(11, Math.min(13, 11*scale*3.5))
      ctx.font = `600 ${fs}px Inter, sans-serif`
      const tw = ctx.measureText(label).width
      const px = 7, py = 4, lh = fs + py*2
      const ly = sy > lh+4 ? sy-lh-2 : sy+2
      ctx.fillStyle = color
      ctx.beginPath(); ctx.roundRect(sx-1, ly, tw+px*2, lh, 4); ctx.fill()
      ctx.fillStyle = 'white'; ctx.fillText(label, sx+px-1, ly+lh-py-1)
    })
  }
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {

  // ── Theme ─────────────────────────────────────────────────────────────────
  const [theme, setTheme] = useState(() => localStorage.getItem('pcb-theme') || 'dark')
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('pcb-theme', theme)
  }, [theme])
  const toggleTheme = () => setTheme(t => t === 'dark' ? 'light' : 'dark')

  // ── Backend Health ─────────────────────────────────────────────────────────
  // null = still checking, true = online, false = offline
  const [backendStatus, setBackendStatus] = useState(null)
  useEffect(() => {
    fetch('/api/')
      .then(r => setBackendStatus(r.ok))
      .catch(()  => setBackendStatus(false))
  }, [])

  // ── Prediction History (persisted in localStorage) ─────────────────────────
  const [history, setHistory] = useState(() => {
    try { return JSON.parse(localStorage.getItem('pcb-history') || '[]') }
    catch { return [] }
  })

  const clearHistory = () => {
    setHistory([])
    localStorage.removeItem('pcb-history')
  }

  // ── Upload & Prediction State ─────────────────────────────────────────────
  const [imageFile,   setImageFile]   = useState(null)
  const [imageUrl,    setImageUrl]    = useState(null)
  const [fileInfo,    setFileInfo]    = useState(null)   // { name, size, compressed }
  const [isDragging,  setIsDragging]  = useState(false)
  const [isLoading,   setIsLoading]   = useState(false)
  const [result,      setResult]      = useState(null)
  const [error,       setError]       = useState(null)
  const [showOverlay, setShowOverlay] = useState(true)

  const fileInputRef = useRef(null)
  const canvasRef    = useRef(null)

  // Redraw canvas when image / result / overlay changes
  useEffect(() => {
    if (!imageUrl) return
    drawCanvas(canvasRef.current, imageUrl, showOverlay && result ? result.regions : [])
  }, [imageUrl, result, showOverlay])

  // Save to history when a new result arrives
  useEffect(() => {
    if (!result || !imageFile) return
    const entry = {
      id         : Date.now(),
      filename   : imageFile.name,
      cls        : result.overall_class,
      confidence : result.overall_confidence,
      time       : new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }
    setHistory(prev => {
      const updated = [entry, ...prev].slice(0, 8)
      localStorage.setItem('pcb-history', JSON.stringify(updated))
      return updated
    })
  }, [result])

  // Ctrl+Enter → trigger predict
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && imageFile && !isLoading) {
        handlePredict()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [imageFile, isLoading])

  // ── File handling ─────────────────────────────────────────────────────────
  const handleFile = useCallback(async (file) => {
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setError('Please upload a JPG or PNG image file.'); return
    }
    const isLarge = file.size > 5 * 1024 * 1024
    const processed = isLarge ? await compressImage(file) : file

    setImageFile(processed)
    setFileInfo({
      name      : file.name,
      origSize  : formatBytes(file.size),
      finalSize : formatBytes(processed.size),
      compressed: isLarge,
    })
    setResult(null); setError(null); setShowOverlay(true)
    setImageUrl(URL.createObjectURL(processed))
  }, [])

  const handleFileChange = (e) => handleFile(e.target.files[0])
  const handleDrop = (e) => {
    e.preventDefault(); setIsDragging(false); handleFile(e.dataTransfer.files[0])
  }
  const handleReset = () => {
    setImageUrl(null); setImageFile(null); setFileInfo(null)
    setResult(null);   setError(null);     setShowOverlay(true)
  }

  // ── API Call ──────────────────────────────────────────────────────────────
  const handlePredict = async () => {
    if (!imageFile) return
    setIsLoading(true); setError(null)
    try {
      const fd = new FormData(); fd.append('file', imageFile)
      const res = await fetch(`${API_BASE}/predict`, { method: 'POST', body: fd })
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Prediction failed') }
      setResult(await res.json())
    } catch (err) { setError(err.message) }
    finally { setIsLoading(false) }
  }

  // ── Download annotated image ──────────────────────────────────────────────
  const handleDownload = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    const link     = document.createElement('a')
    link.download  = `pcb-${result?.overall_class || 'result'}-${Date.now()}.png`
    link.href      = canvas.toDataURL('image/png')
    link.click()
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="app">

      {/* ── Header ── */}
      <header className="header">
        <div className="header-logo"><LogoPCB size={40} /></div>
        <div className="header-text" style={{ marginLeft: 12 }}>
          <div className="header-title">PCB Defect Detection</div>
          <div className="header-subtitle">
            EfficientNet-B0 &middot; 99.1% Accuracy &middot; 6 Defect Classes
          </div>
        </div>
        <div className="header-right">
          <div className="header-badge">
            <span className="header-badge-dot" /> AI Live
          </div>
          <button className="theme-btn" onClick={toggleTheme}
            title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}>
            {theme === 'dark' ? <IconSun size={17} /> : <IconMoon size={17} />}
          </button>
        </div>
      </header>

      {/* ── Health Banner ── */}
      {backendStatus === false && (
        <div className="health-banner offline">
          <IconWifiOff size={15} />
          Backend offline — make sure FastAPI is running on port 8000
        </div>
      )}
      {backendStatus === null && (
        <div className="health-banner checking">
          <IconServer size={15} />
          Connecting to backend...
        </div>
      )}

      {/* ── Stats Bar ── */}
      <div className="stats-bar">
        {MODEL_STATS.map(s => (
          <div key={s.label} className="stat-item">
            <span className="stat-icon"><IconZap size={12} /></span>
            <span className="stat-label">{s.label}</span>
            <span className="stat-value">{s.value}</span>
          </div>
        ))}
      </div>

      {/* ── Main Grid ── */}
      <main className="main">

        {/* LEFT — Upload */}
        <div>
          <div className="card">
            <div className="card-header">
              <span className="card-icon"><IconUpload size={16} /></span>
              <span className="card-title">Upload PCB Image</span>
            </div>

            {/* File info strip — shown after file selected */}
            {fileInfo && (
              <div className="file-info">
                <span className="file-info-icon"><IconFile size={16} /></span>
                <div className="file-info-details">
                  <div className="file-info-name">{fileInfo.name}</div>
                  <div className="file-info-meta">
                    {fileInfo.compressed
                      ? `Compressed: ${fileInfo.origSize} → ${fileInfo.finalSize}`
                      : fileInfo.finalSize
                    }
                  </div>
                </div>
                <span className={`file-info-badge ${fileInfo.compressed ? 'badge-large' : 'badge-ok'}`}>
                  {fileInfo.compressed ? 'Compressed' : 'Ready'}
                </span>
              </div>
            )}

            {imageUrl ? (
              <>
                <div className="preview-wrap">
                  <canvas ref={canvasRef} style={{ width: '100%', display: 'block' }} />
                </div>

                {result && (
                  <div className="overlay-toggle">
                    <span className="overlay-toggle-label">
                      <IconTarget size={14} color="var(--accent-light)" />
                      Defect Overlay
                    </span>
                    <button
                      className={`toggle-btn ${showOverlay ? 'toggle-on' : 'toggle-off'}`}
                      onClick={() => setShowOverlay(p => !p)}>
                      <span className="toggle-thumb" />
                    </button>
                    <span className="overlay-toggle-status"
                      style={{ color: showOverlay ? 'var(--success)' : 'var(--text-muted)' }}>
                      {showOverlay ? 'ON' : 'OFF'}
                    </span>
                  </div>
                )}

                {/* Download button — only when result is ready */}
                {result && (
                  <button className="download-btn" onClick={handleDownload}>
                    <IconDownload size={15} /> Download Annotated Image
                  </button>
                )}

                <button className="change-btn" onClick={handleReset} style={{ marginTop: 10 }}>
                  <IconX size={14} /> Remove image
                </button>
              </>
            ) : (
              <div
                className={`upload-zone ${isDragging ? 'drag-over' : ''}`}
                onClick={() => fileInputRef.current.click()}
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={handleDrop}>
                <div className="upload-zone-icon"><IconImage size={26} /></div>
                <div className="upload-text">Drag &amp; drop PCB image here</div>
                <div className="upload-hint">or click to browse &middot; JPG, PNG</div>
              </div>
            )}

            <input type="file" accept="image/*" ref={fileInputRef}
              onChange={handleFileChange} style={{ display: 'none' }} />

            <button className="predict-btn" onClick={handlePredict}
              disabled={!imageFile || isLoading}>
              {isLoading
                ? <><div className="spinner" /> Analyzing...</>
                : <><IconScan size={17} /> Detect Defect</>
              }
            </button>

            {/* Keyboard shortcut hint */}
            {imageFile && !isLoading && (
              <div className="kbd-hint">
                <span className="kbd">Ctrl</span>+<span className="kbd">Enter</span>
                to detect
              </div>
            )}

            {error && (
              <div className="error-box">
                <IconAlert size={16} />{error}
              </div>
            )}
          </div>
        </div>

        {/* RIGHT — Results */}
        <div>
          <div className="card">
            <div className="card-header">
              <span className="card-icon"><IconChart size={16} /></span>
              <span className="card-title">Detection Results</span>
            </div>

            {isLoading ? (
              <SkeletonResults />
            ) : result ? (
              <>
                <div className="verdict">
                  <div className="verdict-label">Detected Defect</div>
                  <div className="verdict-class"
                    style={{ color: CLASS_COLORS[result.overall_class] || 'white' }}>
                    {result.overall_class.replace(/_/g, ' ')}
                  </div>
                  <div className="verdict-confidence">
                    {result.overall_confidence}% confidence
                  </div>
                  {!result.has_annotation && (
                    <div className="verdict-note">
                      <IconAlert size={12} /> Centre crop used — no annotation found
                    </div>
                  )}
                </div>

                <div className="section-label">
                  <IconLayers size={13} /> Class Probabilities
                </div>
                <div className="prob-list">
                  {Object.entries(result.all_class_probs)
                    .sort(([,a],[,b]) => b - a)
                    .map(([name, value]) => (
                      <ConfidenceBar key={name} name={name} value={value}
                        isTop={name === result.overall_class} />
                    ))}
                </div>

                {result.regions.length > 0 && (
                  <>
                    <div className="divider" />
                    <div className="section-label">
                      <IconMapPin size={13} /> Detected Regions ({result.regions.length})
                    </div>
                    <div className="regions">
                      {result.regions.map((r, i) => <RegionCard key={i} region={r} index={i} />)}
                    </div>
                  </>
                )}
              </>
            ) : (
              <div className="empty-state">
                <div className="empty-icon-wrap"><IconTarget size={28} /></div>
                <div className="empty-title">No Results Yet</div>
                <div className="empty-sub">
                  Upload a PCB image and click<br />
                  <strong>Detect Defect</strong> to begin analysis
                </div>
              </div>
            )}
          </div>
        </div>
      </main>

      {/* ── Prediction History ── */}
      <section className="history-section">
        <div className="history-card">
          <div className="card-header">
            <span className="card-icon"><IconHistory size={16} /></span>
            <span className="card-title">Recent Predictions</span>
            {history.length > 0 && (
              <button className="clear-btn" onClick={clearHistory}>Clear</button>
            )}
          </div>

          {history.length === 0 ? (
            <div className="history-empty">No predictions yet — run your first detection above</div>
          ) : (
            <div className="history-list">
              {history.map(h => {
                const color = CLASS_COLORS[h.cls] || '#7c3aed'
                return (
                  <div className="history-item" key={h.id} style={{ borderLeftColor: color }}>
                    <div className="history-dot" style={{ background: color }} />
                    <span className="history-class" style={{ color }}>{h.cls.replace(/_/g, ' ')}</span>
                    <span className="history-file">{h.filename}</span>
                    <span className="history-conf">{h.confidence}%</span>
                    <span className="history-time">{h.time}</span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </section>

      <footer className="footer">
        PCB Defect Detection &nbsp;&middot;&nbsp; EfficientNet-B0
        &nbsp;&middot;&nbsp; DeepPCB Dataset &nbsp;&middot;&nbsp; 99.1% Val Accuracy
      </footer>

    </div>
  )
}
