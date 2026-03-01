import { useEffect, useRef, useState } from 'react'
import { apiFetch, apiUpload } from '../api/client'

const STATUS_STYLES = {
  pending:    'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
  processing: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  completed:  'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  failed:     'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
}

export default function DocumentsPage({ token }) {
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const fileRef = useRef()

  async function fetchDocuments() {
    try {
      const data = await apiFetch('/api/v1/sop/documents', { token })
      setDocuments(data)
    } catch {
      // keep stale data on polling errors
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDocuments()
    const interval = setInterval(fetchDocuments, 5000)
    return () => clearInterval(interval)
  }, [token])

  async function handleUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadError('')
    setUploading(true)
    try {
      await apiUpload('/api/v1/sop/ingest', { token, file })
      await fetchDocuments()
    } catch (err) {
      setUploadError(err.message)
    } finally {
      setUploading(false)
      fileRef.current.value = ''
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-gray-900 dark:text-white">Documents</h1>
        <div className="flex items-center gap-3">
          {uploadError && (
            <span className="text-sm text-red-600 dark:text-red-400">{uploadError}</span>
          )}
          <label className="cursor-pointer">
            <input
              ref={fileRef}
              type="file"
              accept=".pdf"
              className="hidden"
              onChange={handleUpload}
              disabled={uploading}
            />
            <span className={`inline-block px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors ${
              uploading
                ? 'bg-indigo-400 cursor-not-allowed'
                : 'bg-indigo-600 hover:bg-indigo-700'
            }`}>
              {uploading ? 'Uploading…' : 'Upload PDF'}
            </span>
          </label>
        </div>
      </div>

      {loading ? (
        <p className="text-gray-500 dark:text-gray-400 text-sm">Loading…</p>
      ) : documents.length === 0 ? (
        <div className="text-center py-16 text-gray-400 dark:text-gray-600">
          <p className="text-lg mb-2">No documents yet</p>
          <p className="text-sm">Upload a PDF to get started.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800 text-left">
              <tr>
                <th className="px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Filename</th>
                <th className="px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Status</th>
                <th className="px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Version</th>
                <th className="px-4 py-3 font-medium text-gray-600 dark:text-gray-300">Uploaded</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {documents.map(doc => (
                <tr key={doc.document_id} className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                  <td className="px-4 py-3 text-gray-900 dark:text-white font-medium">{doc.filename}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${STATUS_STYLES[doc.status] || ''}`}>
                      {doc.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">v{doc.version}</td>
                  <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
                    {new Date(doc.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
