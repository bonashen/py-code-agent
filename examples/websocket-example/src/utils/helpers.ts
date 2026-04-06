export const FILE_TYPE_ICONS: Record<string, string> = {
  pdf: '📄',
  doc: '📝',
  docx: '📝',
  xls: '📊',
  xlsx: '📊',
  ppt: '📽️',
  pptx: '📽️',
  zip: '📦',
  rar: '📦',
  jpg: '🖼️',
  jpeg: '🖼️',
  png: '🖼️',
  gif: '🖼️',
  svg: '🖼️',
  mp3: '🎵',
  wav: '🎵',
  mp4: '🎬',
  mov: '🎬',
  txt: '📃',
  md: '📝',
  json: '📋',
  js: '💻',
  ts: '💻',
  py: '🐍',
  default: '📎',
}

export function getFileIcon(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  return FILE_TYPE_ICONS[ext] || FILE_TYPE_ICONS.default
}

export function generateId(): string {
  return Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15)
}

export function formatTimestamp(timestamp: number): string {
  const date = new Date(timestamp)
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()
  
  if (isToday) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + 
         date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function decodeBase64ToBlob(base64: string, filename: string): Blob {
  const byteCharacters = atob(base64)
  const byteNumbers = new Array(byteCharacters.length)
  for (let i = 0; i < byteCharacters.length; i++) {
    byteNumbers[i] = byteCharacters.charCodeAt(i)
  }
  const byteArray = new Uint8Array(byteNumbers)
  const mimeType = getMimeType(filename)
  return new Blob([byteArray], { type: mimeType })
}

export function getMimeType(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  const mimeTypes: Record<string, string> = {
    pdf: 'application/pdf',
    doc: 'application/msword',
    docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    xls: 'application/vnd.ms-excel',
    xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    ppt: 'application/vnd.ms-powerpoint',
    pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    zip: 'application/zip',
    rar: 'application/x-rar-compressed',
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    png: 'image/png',
    gif: 'image/gif',
    svg: 'image/svg+xml',
    mp3: 'audio/mpeg',
    wav: 'audio/wav',
    mp4: 'video/mp4',
    mov: 'video/quicktime',
    txt: 'text/plain',
    md: 'text/markdown',
    json: 'application/json',
    js: 'text/javascript',
    ts: 'text/typescript',
    py: 'text/x-python',
  }
  return mimeTypes[ext] || 'application/octet-stream'
}

export function downloadFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
