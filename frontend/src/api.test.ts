import { afterEach, describe, expect, it, vi } from 'vitest'

import { deleteJob, errorFrom, getJob, submitJob } from './api'
import { json, makeJob } from './test/jobs'

afterEach(() => vi.unstubAllGlobals())

describe('errorFrom', () => {
  it('uses a string detail as the message', () => {
    const e = errorFrom(400, { detail: 'No files were uploaded.' })
    expect(e.status).toBe(400)
    expect(e.message).toBe('No files were uploaded.')
    expect(e.ignored).toEqual([])
  })

  it('reads message and ignored files from an object detail', () => {
    const ignored = [{ name: 'x.docx', reason: 'not a supported file type' }]
    const e = errorFrom(422, { detail: { message: 'None of the files can be read.', ignored } })
    expect(e.message).toBe('None of the files can be read.')
    expect(e.ignored).toEqual(ignored)
  })

  it('turns a validation list into a plain sentence', () => {
    const e = errorFrom(422, { detail: [{ loc: ['body', 'evaluation_date'], msg: 'bad date' }] })
    expect(e.message).toBe('Some of the entered values are not valid.')
  })

  it('says the server is unreachable for status 0, and names the status otherwise', () => {
    expect(errorFrom(0, null).message).toMatch(/could not be reached/)
    expect(errorFrom(502, 'Bad Gateway').message).toBe('The server answered with an error (502).')
  })
})

describe('requests', () => {
  it('send the X-HKLV header', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(json(makeJob()))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetch)
    await getJob('j1')
    await deleteJob('j1')
    for (const [, init] of fetch.mock.calls) expect((init as RequestInit).headers).toMatchObject({ 'X-HKLV': '1' })
    expect(fetch.mock.calls[1]?.[1]).toMatchObject({ method: 'DELETE' })
  })

  it('submitJob rejects at once when already cancelled, without uploading', async () => {
    const open = vi.spyOn(XMLHttpRequest.prototype, 'open')
    const controller = new AbortController()
    controller.abort()
    await expect(submitJob([], { online: true }, () => {}, controller.signal)).rejects.toMatchObject({
      name: 'AbortError',
    })
    expect(open).not.toHaveBeenCalled()
    open.mockRestore()
  })
})
