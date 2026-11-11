/** What the user has picked on the upload screen. Kept by App, so it survives an upload error. */
export interface Draft {
  files: File[]
  caseId: string
  evaluationDate: string
  online: boolean
}

export const EMPTY_DRAFT: Draft = { files: [], caseId: '', evaluationDate: '', online: true }
