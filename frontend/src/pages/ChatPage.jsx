import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { apiFetch } from '../api/client'

// Strip inline [Source N] / [Source 1] markers the LLM may emit.
// The source chips below the answer already serve that purpose.
function stripSourceRefs(text) {
  return text.replace(/\s*\[Source\s+\d+\]/gi, '').trim()
}


function SourceChip({ source, isOpen, onToggle }) {
  const label =
    source.page_number != null
      ? `${source.document_filename} — Page ${source.page_number}`
      : source.document_filename

  return (
    <span className="relative">
      <button
        onClick={onToggle}
        className="inline-block bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 text-xs px-2 py-0.5 rounded-full hover:bg-indigo-100 dark:hover:bg-indigo-900/50 hover:text-indigo-700 dark:hover:text-indigo-300 transition-colors cursor-pointer"
        title={`Relevance: ${source.relevance_score?.toFixed(3)} — click to view passage`}
      >
        {label}
      </button>

      {isOpen && (
        <div className="absolute bottom-full left-0 mb-1.5 z-20 w-80 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 rounded-xl shadow-xl p-3">
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">
            {source.document_filename}
            {source.page_number != null && (
              <span className="ml-1 text-indigo-500 dark:text-indigo-400">— Page {source.page_number}</span>
            )}
          </p>
          <p className="text-xs text-gray-700 dark:text-gray-200 whitespace-pre-wrap leading-relaxed max-h-40 overflow-y-auto">
            {source.chunk_text}
          </p>
        </div>
      )}
    </span>
  )
}

export default function ChatPage({ token }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  // Tracks which source chip has its popover open: { msgIdx, srcIdx } | null
  const [openSource, setOpenSource] = useState(null)
  const bottomRef = useRef()

  // Close any open popover when clicking outside
  useEffect(() => {
    function handleClickOutside() {
      setOpenSource(null)
    }
    document.addEventListener('click', handleClickOutside)
    return () => document.removeEventListener('click', handleClickOutside)
  }, [])

  async function handleSubmit(e) {
    e.preventDefault()
    const question = input.trim()
    if (!question || loading) return

    setMessages(prev => [...prev, { role: 'user', text: question }])
    setInput('')
    setLoading(true)
    setOpenSource(null)

    try {
      const requestBody = { query: question }
      console.log('[ChatPage] POST /api/v1/sop/query body:', requestBody)
      const data = await apiFetch('/api/v1/sop/query', {
        token,
        method: 'POST',
        body: requestBody,
      })
      console.log('[ChatPage] API response:', data)
      console.log('[ChatPage] sources_relevant:', data.sources_relevant)
      console.log('[ChatPage] sources:', data.sources)
      const msg = {
        role: 'assistant',
        text: data.answer,
        sources: data.sources || [],
        sources_relevant: data.sources_relevant,
      }
      console.log('[ChatPage] message object stored in state:', msg)
      setMessages(prev => [...prev, msg])
    } catch (err) {
      setMessages(prev => [...prev, { role: 'error', text: err.message }])
    } finally {
      setLoading(false)
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
    }
  }

  function toggleSource(msgIdx, srcIdx, e) {
    e.stopPropagation() // prevent the document click handler from immediately closing it
    setOpenSource(prev =>
      prev?.msgIdx === msgIdx && prev?.srcIdx === srcIdx
        ? null
        : { msgIdx, srcIdx }
    )
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 flex flex-col h-[calc(100vh-64px)]">
      <h1 className="text-xl font-bold text-gray-900 dark:text-white mb-4">Chat</h1>

      <div className="flex-1 overflow-y-auto space-y-4 mb-4">
        {messages.length === 0 && (
          <div className="text-center py-16 text-gray-400 dark:text-gray-600">
            <p className="text-lg mb-2">Ask a question about your SOPs</p>
            <p className="text-sm">Answers are grounded in your uploaded documents.</p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>

            {msg.role === 'user' && (
              <div className="max-w-[75%] bg-indigo-600 text-white rounded-2xl rounded-tr-sm px-4 py-2 text-sm">
                {msg.text}
              </div>
            )}

            {msg.role === 'assistant' && (
              <div className="max-w-[85%] space-y-2">
                <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl rounded-tl-sm px-4 py-3">
                  <div className="prose prose-sm dark:prose-invert max-w-none text-gray-900 dark:text-white">
                    <ReactMarkdown>
                      {stripSourceRefs(msg.text)}
                    </ReactMarkdown>
                  </div>
                </div>

                {msg.sources_relevant && msg.sources?.length > 0 && (
                  <div className="flex flex-wrap gap-1 pl-1">
                    {msg.sources.map((s, j) => (
                      <SourceChip
                        key={j}
                        source={s}
                        isOpen={openSource?.msgIdx === i && openSource?.srcIdx === j}
                        onToggle={e => toggleSource(i, j, e)}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}

            {msg.role === 'error' && (
              <div className="max-w-[85%] bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 rounded-2xl px-4 py-2 text-sm">
                Error: {msg.text}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl rounded-tl-sm px-4 py-3">
              <span className="inline-flex gap-1">
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0ms]" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
              </span>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Ask about your SOPs…"
          disabled={loading}
          className="flex-1 px-4 py-2 rounded-xl border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-sm font-medium rounded-xl transition-colors"
        >
          Send
        </button>
      </form>
    </div>
  )
}
