import { useState } from 'react'
import { api, ApiError } from './api/client'

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export default function App() {
  const [log, setLog] = useState<string[]>([])
  const write = (line: string) => setLog((prev) => [...prev, line])

  async function runTest(file: File) {
    setLog([])
    try {
      const dossier = await api.createDossier('Hồ sơ thử')
      write(`1. Tạo hồ sơ: ${dossier.id}`)

      const upload = await api.uploadFile(dossier.id, file)
      write(`2. Upload "${upload.original_name}" → job ${upload.job_id} (${upload.job_status})`)

      // Poll job mỗi 2 giây cho tới khi xong (contract mục 3.3)
      let job = await api.getJob(upload.job_id)
      while (job.status === 'queued' || job.status === 'running') {
        write(`3. Job đang ${job.status}…`)
        await sleep(2000)
        job = await api.getJob(upload.job_id)
      }

      if (job.status === 'failed') {
        write(`Job lỗi: ${job.error_message}`)
        return
      }

      const result = await api.getJobResult(job.id)
      write(`4. Kết quả: ${result.documents.length} chứng từ, engine ${result.engine_version}`)
      console.log('AnalysisResult', result)
    } catch (err) {
      if (err instanceof ApiError) write(`${err.status}: ${err.message}`)
      else throw err
    }
  }

  return (
    <main style={{ padding: 24, fontFamily: 'sans-serif' }}>
      <h1>Thử API</h1>
      <input
        type="file"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) runTest(file)
        }}
      />
      <pre>{log.join('\n')}</pre>
    </main>
  )
}