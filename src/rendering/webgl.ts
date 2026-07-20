export function createProgram(gl: WebGL2RenderingContext, vertexSource: string, fragmentSource: string) {
  const compile = (type: number, source: string) => {
    const shader = gl.createShader(type)
    if (!shader) throw new Error('Unable to allocate WebGL shader')
    gl.shaderSource(shader, source); gl.compileShader(shader)
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const message = gl.getShaderInfoLog(shader) ?? 'Shader compilation failed'; gl.deleteShader(shader); throw new Error(message)
    }
    return shader
  }
  const vertex = compile(gl.VERTEX_SHADER, vertexSource)
  const fragment = compile(gl.FRAGMENT_SHADER, fragmentSource)
  const program = gl.createProgram()
  if (!program) throw new Error('Unable to allocate WebGL program')
  gl.attachShader(program, vertex); gl.attachShader(program, fragment); gl.linkProgram(program)
  gl.deleteShader(vertex); gl.deleteShader(fragment)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program) ?? 'Program linking failed')
  return program
}

export function resizeCanvas(canvas: HTMLCanvasElement) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2.5)
  const rect = canvas.getBoundingClientRect()
  const width = Math.max(1, Math.round(rect.width * dpr)); const height = Math.max(1, Math.round(rect.height * dpr))
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; return true }
  return false
}

export function turboLut() {
  const data = new Uint8Array(256 * 4)
  const stops = [[0, 4, 14, 44], [.18, 31, 64, 173], [.38, 0, 196, 214], [.56, 32, 232, 124], [.74, 231, 225, 35], [.88, 246, 105, 18], [1, 122, 4, 3]]
  for (let i = 0; i < 256; i++) {
    const x = i / 255; let s = 0; while (s < stops.length - 2 && x > stops[s + 1][0]) s++
    const a = stops[s]; const b = stops[s + 1]; const t = (x - a[0]) / (b[0] - a[0])
    data[i * 4] = a[1] + (b[1] - a[1]) * t; data[i * 4 + 1] = a[2] + (b[2] - a[2]) * t
    data[i * 4 + 2] = a[3] + (b[3] - a[3]) * t; data[i * 4 + 3] = 255
  }
  return data
}
