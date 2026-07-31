import { createProgram } from "./webgl";
import type { Viewport } from "../types";
import { plotRectFramebuffer } from "./plotGeometry";

export function spectrumPanPixelsToClip(
  offsetPx: number,
  plotWidthPx: number,
) {
  return plotWidthPx > 0 ? 2 * offsetPx / plotWidthPx : 0;
}

export function accumulateSpectrumIntervalMax(
  current: Float32Array | null,
  values: Float32Array,
): Float32Array {
  if (!current || current.length !== values.length) return values.slice();
  for (let index = 0; index < values.length; index++)
    if (values[index] > current[index]) current[index] = values[index];
  return current;
}

export interface PendingSpectrumSummary {
  latest: Float32Array;
  maximum: Float32Array;
  framesMerged: number;
}
export function mergePendingSpectrum(
  previous: PendingSpectrumSummary | null,
  latest: Float32Array,
  maximum: Float32Array,
): PendingSpectrumSummary {
  if (latest.length !== maximum.length)
    throw new Error("Temporal spectrum arrays must have matching lengths");
  if (!previous || previous.latest.length !== latest.length)
    return { latest, maximum: maximum.slice(), framesMerged: 1 };
  return {
    latest,
    maximum: accumulateSpectrumIntervalMax(previous.maximum, maximum),
    framesMerged: previous.framesMerged + 1,
  };
}

export class SpectrumRenderer {
  private gl: WebGL2RenderingContext;
  private program: WebGLProgram;
  private vao: WebGLVertexArrayObject;
  private buffer: WebGLBuffer;
  private current: Float32Array | null = null;
  private intervalMax: Float32Array | null = null;
  private configurationGeneration: number | null = null;
  private panOffsetClip = 0;
  private panDimmed = false;
  constructor(private canvas: HTMLCanvasElement) {
    const gl = canvas.getContext("webgl2", { antialias: true, alpha: true });
    if (!gl) throw new Error("WebGL2 is required for the spectrum");
    this.gl = gl;
    this.program = createProgram(
      gl,
      `#version 300 es
      in float amplitude; uniform vec2 frequencyView; uniform vec2 amplitudeView; uniform float pointCount; uniform float panOffsetClip;
      void main(){ float x=(float(gl_VertexID)+0.5)/max(1.0,pointCount); float px=(x-frequencyView.x)/(frequencyView.y-frequencyView.x)*2.0-1.0+panOffsetClip; float py=(amplitude-amplitudeView.x)/(amplitudeView.y-amplitudeView.x)*2.0-1.0; gl_Position=vec4(px,py,0,1); }`,
      `#version 300 es
      precision mediump float; uniform vec4 traceColor; out vec4 color; void main(){ color=traceColor; }`,
    );
    const vao = gl.createVertexArray();
    const buffer = gl.createBuffer();
    if (!vao || !buffer)
      throw new Error("Unable to allocate spectrum resources");
    this.vao = vao;
    this.buffer = buffer;
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    const location = gl.getAttribLocation(this.program, "amplitude");
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location, 1, gl.FLOAT, false, 0, 0);
  }
  setPanOffsetPixels(offsetPx: number, plotWidthPx: number) {
    this.panOffsetClip = spectrumPanPixelsToClip(offsetPx, plotWidthPx);
  }
  setPanDimmed(dimmed: boolean) {
    this.panDimmed = dimmed;
  }
  setFrame(
    values: Float32Array,
    intervalMaximum: Float32Array = values,
    configurationGeneration?:number,
  ) {
    if (values.length !== intervalMaximum.length)
      throw new Error("Temporal spectrum arrays must have matching lengths");
    if(
      configurationGeneration!==undefined&&
      configurationGeneration!==this.configurationGeneration
    ){
      if(this.configurationGeneration!==null)this.intervalMax=null
      this.configurationGeneration=configurationGeneration
    }
    this.current = values;
    this.intervalMax = accumulateSpectrumIntervalMax(
      this.intervalMax,
      intervalMaximum,
    );
  }
  render(view: Viewport, persistence: boolean) {
    if (!this.current) return;
    const gl = this.gl;
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0.018, 0.027, 0.035, 1);
    gl.clear(gl.COLOR_BUFFER_BIT);
    const plot=plotRectFramebuffer(Math.max(1,this.canvas.clientWidth),this.canvas.width)
    const verticalScale=this.canvas.height/Math.max(1,this.canvas.clientHeight)
    gl.viewport(plot.left,Math.round(27*verticalScale),plot.width,Math.max(1,this.canvas.height-Math.round(34*verticalScale)))
    gl.useProgram(this.program);
    gl.bindVertexArray(this.vao);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    const frequencyView = gl.getUniformLocation(this.program, "frequencyView");
    const amplitudeView = gl.getUniformLocation(this.program, "amplitudeView");
    const pointCount = gl.getUniformLocation(this.program, "pointCount");
    const panOffsetClip = gl.getUniformLocation(this.program, "panOffsetClip");
    const color = gl.getUniformLocation(this.program, "traceColor");
    const draw = (
      data: Float32Array,
      rgba: [number, number, number, number],
    ) => {
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STREAM_DRAW);
      gl.uniform2f(frequencyView, view.start, view.end);
      gl.uniform2f(amplitudeView, view.minDbm, view.maxDbm);
      gl.uniform1f(pointCount, data.length);
      gl.uniform1f(panOffsetClip, this.panOffsetClip);
      gl.uniform4f(
        color,
        rgba[0],
        rgba[1],
        rgba[2],
        this.panDimmed ? rgba[3] * 0.45 : rgba[3],
      );
      gl.drawArrays(gl.LINE_STRIP, 0, data.length);
    };
    if (persistence && this.intervalMax)
      draw(this.intervalMax, [0, 0.72, 1, 0.62]);
    draw(this.current, [1, 0.88, 0.08, 1]);
    this.intervalMax = null;
  }
  dispose() {
    const gl = this.gl;
    gl.deleteBuffer(this.buffer);
    gl.deleteVertexArray(this.vao);
    gl.deleteProgram(this.program);
  }
}
