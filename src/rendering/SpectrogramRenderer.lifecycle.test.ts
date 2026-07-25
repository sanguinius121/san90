import { beforeEach,describe,expect,it,vi } from 'vitest'

vi.mock('./webgl',()=>({
  createProgram:()=>({}),
  turboLut:()=>new Uint8Array(256*4),
}))

import { SpectrogramRenderer } from './SpectrogramRenderer'

function webglStub(){
  return {
    MAX_TEXTURE_SIZE:0x0d33,
    TEXTURE_2D:0x0de1,
    TEXTURE_MIN_FILTER:0x2801,
    TEXTURE_MAG_FILTER:0x2800,
    TEXTURE_WRAP_S:0x2802,
    TEXTURE_WRAP_T:0x2803,
    NEAREST:0x2600,
    LINEAR:0x2601,
    CLAMP_TO_EDGE:0x812f,
    REPEAT:0x2901,
    UNPACK_ALIGNMENT:0x0cf5,
    R8:0x8229,
    RED:0x1903,
    UNSIGNED_BYTE:0x1401,
    RGBA:0x1908,
    getParameter:vi.fn(()=>4096),
    createVertexArray:vi.fn(()=>({})),
    createTexture:vi.fn(()=>({})),
    bindTexture:vi.fn(),
    texParameteri:vi.fn(),
    pixelStorei:vi.fn(),
    texImage2D:vi.fn(),
    texSubImage2D:vi.fn(),
  }
}

describe('spectrogram texture lifecycle',()=>{
  beforeEach(()=>vi.clearAllMocks())

  it('resets generation history in place and reallocates only for a point-count change',()=>{
    const gl=webglStub()
    const canvas={getContext:()=>gl} as unknown as HTMLCanvasElement
    const renderer=new SpectrogramRenderer(canvas)
    expect(gl.texImage2D).toHaveBeenCalledTimes(2)

    renderer.addRows(new Uint8Array(1024),1,1024,0,1)
    renderer.addRows(new Uint8Array(1024),1,1024,1,1)
    expect(renderer.validRowCount).toBe(2)

    renderer.addRows(new Uint8Array(1024),1,1024,0,2)
    expect(renderer.validRowCount).toBe(1)
    expect(gl.texImage2D).toHaveBeenCalledTimes(2)

    renderer.addRows(new Uint8Array(2048),1,2048,0,3)
    expect(renderer.validRowCount).toBe(1)
    expect(renderer.pointCount).toBe(2048)
    expect(gl.texImage2D).toHaveBeenCalledTimes(3)

    renderer.addRows(new Uint8Array(2048),1,2048,1,3)
    expect(renderer.validRowCount).toBe(2)
    expect(gl.texImage2D).toHaveBeenCalledTimes(3)
  })
})
