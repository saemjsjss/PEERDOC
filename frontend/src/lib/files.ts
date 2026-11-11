// What the server accepts (src/hklv_ocr/readers.py SUPPORTED_SUFFIXES, plus ZIP).
export const ACCEPTED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp', '.zip'] as const
export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.join(',')
export const MAX_UPLOAD_BYTES = 150 * 1024 * 1024 // server limit (src/hklv_api/uploads.py)

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot >= 0 ? name.slice(dot).toLowerCase() : ''
}

export function isAccepted(file: Pick<File, 'name'>): boolean {
  return (ACCEPTED_EXTENSIONS as readonly string[]).includes(extensionOf(file.name))
}

export function fileKey(file: Pick<File, 'name' | 'size' | 'lastModified'>): string {
  return `${file.name}|${file.size}|${file.lastModified}`
}

/** Add new files to the selection: drops exact duplicates, separates unsupported files. */
export function mergeFiles(current: File[], incoming: File[]): { files: File[]; rejected: File[] } {
  const seen = new Set(current.map(fileKey))
  const files = [...current]
  const rejected: File[] = []
  for (const file of incoming) {
    if (!isAccepted(file)) {
      rejected.push(file)
      continue
    }
    const key = fileKey(file)
    if (!seen.has(key)) {
      seen.add(key)
      files.push(file)
    }
  }
  return { files, rejected }
}

export function totalBytes(files: Pick<File, 'size'>[]): number {
  return files.reduce((sum, f) => sum + f.size, 0)
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function kindLabel(name: string): string {
  const ext = extensionOf(name)
  if (ext === '.zip') return 'ZIP'
  if (ext === '.pdf') return 'PDF'
  return 'Image'
}
