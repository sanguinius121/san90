import { createProgram, turboLut } from "./webgl";
import type { Viewport } from "../types";
import type { WaterfallFrame } from "../types";
import { plotRectFramebuffer } from "./plotGeometry";

export interface CircularRowUpload {
  sourceRowOffset: number;
  targetRow: number;
  rowCount: number;
}

export interface SpectrogramStateTransition {
  generationChanged:boolean
  pointCountChanged:boolean
  resetHistory:boolean
  reallocateTexture:boolean
}

export function spectrogramStateTransition(
  currentGeneration:number|null,
  currentPointCount:number,
  incomingGeneration:number|undefined,
  incomingPointCount:number,
):SpectrogramStateTransition {
  const generationChanged=
    incomingGeneration!==undefined&&incomingGeneration!==currentGeneration
  const pointCountChanged=incomingPointCount!==currentPointCount
  return {
    generationChanged,
    pointCountChanged,
    resetHistory:generationChanged&&currentGeneration!==null&&!pointCountChanged,
    reallocateTexture:pointCountChanged,
  }
}
export function planCircularRowUploads(
  writeRow: number,
  rowCount: number,
  textureRows: number,
): CircularRowUpload[] {
  if (
    !Number.isInteger(writeRow) ||
    !Number.isInteger(rowCount) ||
    !Number.isInteger(textureRows) ||
    writeRow < 0 ||
    writeRow >= textureRows ||
    rowCount <= 0 ||
    rowCount > textureRows
  )
    throw new Error("Invalid circular waterfall upload dimensions");
  const first = Math.min(rowCount, textureRows - writeRow);
  const uploads: CircularRowUpload[] = [
    { sourceRowOffset: 0, targetRow: writeRow, rowCount: first },
  ];
  if (first < rowCount)
    uploads.push({
      sourceRowOffset: first,
      targetRow: 0,
      rowCount: rowCount - first,
    });
  return uploads;
}

export interface SourceAgeRange { start: number; end: number }
export function sourceAgeRangeForOutputRow(outputRow:number,outputRows:number,visibleRows:number):SourceAgeRange{
  if(!Number.isInteger(outputRow)||!Number.isInteger(outputRows)||!Number.isInteger(visibleRows)||outputRow<0||outputRow>=outputRows||outputRows<1||visibleRows<1)throw new Error("Invalid chronological viewport dimensions")
  const start=Math.floor(outputRow*visibleRows/outputRows)
  const end=Math.min(visibleRows,Math.max(start+1,Math.ceil((outputRow+1)*visibleRows/outputRows)))
  return{start,end}
}

export function chronologicalTextureRow(headRow:number,ageOffset:number,textureRows:number):number{
  if(!Number.isInteger(headRow)||!Number.isInteger(ageOffset)||!Number.isInteger(textureRows)||headRow<0||headRow>=textureRows||ageOffset<0||ageOffset>=textureRows)throw new Error("Invalid circular row age")
  return(headRow-1-ageOffset+textureRows)%textureRows
}

export class CircularWaterfallCursor{
  writeRow=0
  validRows=0
  wraps=0
  constructor(readonly textureRows:number){if(!Number.isInteger(textureRows)||textureRows<1)throw new Error("Texture row capacity must be positive")}
  plan(rowCount:number){return planCircularRowUploads(this.writeRow,rowCount,this.textureRows)}
  commit(rowCount:number){
    if(!Number.isInteger(rowCount)||rowCount<1||rowCount>this.textureRows)throw new Error("Invalid committed row count")
    if(this.writeRow+rowCount>=this.textureRows)this.wraps++
    this.writeRow=(this.writeRow+rowCount)%this.textureRows
    this.validRows=Math.min(this.textureRows,this.validRows+rowCount)
  }
  reset(){this.writeRow=0;this.validRows=0;this.wraps=0}
}

export function debugWaterfallRows(rowCount:number,pointCount:number,firstRowSequence:number):Uint8Array{
  if(rowCount<1||pointCount<1||!Number.isInteger(firstRowSequence)||firstRowSequence<0)throw new Error("Invalid debug waterfall dimensions")
  const values=new Uint8Array(rowCount*pointCount)
  for(let row=0;row<rowCount;row++)values.fill((firstRowSequence+row)%255+1,row*pointCount,(row+1)*pointCount)
  return values
}

export function verticalMaxPoolCircularRows(texture:Uint8Array,textureRows:number,pointCount:number,headRow:number,visibleRows:number,outputRows:number):Uint8Array{
  if(texture.length!==textureRows*pointCount||visibleRows<1||visibleRows>textureRows||outputRows<1)throw new Error("Invalid circular max-pool dimensions")
  const output=new Uint8Array(outputRows*pointCount)
  for(let target=0;target<outputRows;target++){
    const range=sourceAgeRangeForOutputRow(target,outputRows,visibleRows)
    for(let age=range.start;age<range.end;age++){
      const sourceRow=chronologicalTextureRow(headRow,age,textureRows)
      for(let point=0;point<pointCount;point++)output[target*pointCount+point]=Math.max(output[target*pointCount+point],texture[sourceRow*pointCount+point])
    }
  }
  return output
}
export const waterfallHistorySeconds = (
  textureRows: number,
  rowsPerSecond: number,
) => {
  if (textureRows <= 0 || rowsPerSecond <= 0 || !Number.isFinite(rowsPerSecond))
    throw new Error("Waterfall history dimensions must be positive");
  return textureRows / rowsPerSecond;
};
export const waterfallVisibleRows = (
  rowsPerSecond: number,
  visibleTimeSpanSeconds = 5,
) => {
  if (
    rowsPerSecond <= 0 ||
    visibleTimeSpanSeconds <= 0 ||
    !Number.isFinite(rowsPerSecond) ||
    !Number.isFinite(visibleTimeSpanSeconds)
  )
    throw new Error("Visible waterfall dimensions must be positive");
  return Math.max(1, Math.round(rowsPerSecond * visibleTimeSpanSeconds));
};
export const visibleTextureRow = (
  headRow: number,
  normalizedAge: number,
  visibleRows: number,
  textureRows: number,
) => {
  if (
    !Number.isInteger(headRow) ||
    headRow < 0 ||
    headRow >= textureRows ||
    normalizedAge < 0 ||
    normalizedAge > 1 ||
    visibleRows <= 0 ||
    visibleRows > textureRows
  )
    throw new Error("Invalid visible waterfall viewport");
  return (
    (headRow -
      1 -
      Math.round(normalizedAge * Math.max(0, visibleRows - 1)) +
      textureRows) %
    textureRows
  );
};
export function verticalMaxPoolRows(
  values: Uint8Array,
  rowCount: number,
  pointCount: number,
  outputRows: number,
): Uint8Array {
  if (
    rowCount <= 0 ||
    pointCount <= 0 ||
    outputRows <= 0 ||
    outputRows > rowCount ||
    values.length !== rowCount * pointCount
  )
    throw new Error("Invalid vertical max-pool dimensions");
  const output = new Uint8Array(outputRows * pointCount);
  for (let target = 0; target < outputRows; target++) {
    const start = Math.floor((target * rowCount) / outputRows),
      end = Math.max(
        start + 1,
        Math.ceil(((target + 1) * rowCount) / outputRows),
      );
    for (let source = start; source < end; source++)
      for (let point = 0; point < pointCount; point++)
        output[target * pointCount + point] = Math.max(
          output[target * pointCount + point],
          values[source * pointCount + point],
        );
  }
  return output;
}
export class BoundedWaterfallBatchBuffer {
  private pending: WaterfallFrame[] = [];
  private lastGeneration: number | null = null;
  private lastBatchSequence: number | null = null;
  replacedBatches = 0;
  replacedRows = 0;
  outOfOrderBatches=0;
  outOfOrderRows=0;
  constructor(private readonly capacity = 16) {
    if (!Number.isInteger(capacity) || capacity < 2)
      throw new Error("Waterfall batch capacity must be at least two");
  }
  push(frame: WaterfallFrame) {
    if(this.lastGeneration!==frame.configurationGeneration){this.lastGeneration=frame.configurationGeneration;this.lastBatchSequence=null;this.pending=[]}
    if(this.lastBatchSequence!==null&&frame.batchSequence<=this.lastBatchSequence){this.outOfOrderBatches++;this.outOfOrderRows+=frame.rowCount;return}
    this.lastBatchSequence=frame.batchSequence
    if (this.pending.length >= this.capacity) {
      const older = this.pending.shift()!,
        newer = this.pending[0];
      if (
        older.configurationGeneration === newer.configurationGeneration &&
        older.pointCount === newer.pointCount &&
        older.rowCount === newer.rowCount
      ) {
        for (let index = 0; index < newer.values.length; index++)
          if (older.values[index] > newer.values[index])
            newer.values[index] = older.values[index];
      }
      this.replacedBatches++;
      this.replacedRows += older.rowCount;
    }
    this.pending.push(frame);
  }
  drain(): WaterfallFrame[] {
    const frames = this.pending;
    this.pending = [];
    return frames;
  }
  clear() {
    this.pending = [];
    this.lastGeneration=null;
    this.lastBatchSequence=null;
  }
  get size() {
    return this.pending.length;
  }
}

export class SpectrogramRenderer {
  private gl: WebGL2RenderingContext;
  private program: WebGLProgram;
  private vao: WebGLVertexArrayObject;
  private dataTexture: WebGLTexture;
  private lutTexture: WebGLTexture;
  private rows: number;
  private points = 1024;
  private cursor: CircularWaterfallCursor;
  private configurationGeneration:number|null=null;
  constructor(
    private canvas: HTMLCanvasElement,
    textureRows = 4096,
    private readonly debugRows = false,
  ) {
    const gl = canvas.getContext("webgl2", { antialias: false, alpha: false });
    if (!gl) throw new Error("WebGL2 is required for the spectrogram");
    this.gl = gl;
    this.rows = Math.min(
      textureRows,
      gl.getParameter(gl.MAX_TEXTURE_SIZE) as number,
    );
    if (this.rows < 2400)
      throw new Error(
        "WebGL texture must retain at least five seconds at 480 rows/s",
      );
    this.cursor=new CircularWaterfallCursor(this.rows)
    this.program = createProgram(
      gl,
      `#version 300 es
      out vec2 uv; void main(){ vec2 p=vec2((gl_VertexID<<1)&2, gl_VertexID&2); uv=p; gl_Position=vec4(p*2.0-1.0,0,1); }`,
      `#version 300 es
      precision highp float; in vec2 uv; out vec4 color; uniform sampler2D dataTex; uniform sampler2D lut; uniform float head; uniform float textureRows; uniform float visibleRows; uniform float validRows; uniform float outputHeight; uniform vec2 view;
      void main(){
        float sourceStart=gl_FragCoord.y*visibleRows/max(1.0,outputHeight);
        float sourceEnd=(gl_FragCoord.y+1.0)*visibleRows/max(1.0,outputHeight);
        int firstAgeOffset=int(floor(sourceStart));
        if(float(firstAgeOffset)>=validRows){color=vec4(0.018,0.027,0.035,1.0);return;}
        int lastAgeOffset=min(int(validRows),max(firstAgeOffset+1,int(ceil(sourceEnd))));
        float v=0.0;
        int sampleCount=lastAgeOffset-firstAgeOffset;
        for(int sampleIndex=0;sampleIndex<sampleCount;sampleIndex++){
          float age=1.0+float(firstAgeOffset+sampleIndex);
          float y=fract(head-(age-0.5)/textureRows);
          v=max(v,texture(dataTex,vec2(mix(view.x,view.y,uv.x),y)).r);
        }
        color=texture(lut,vec2(v,.5));
      }`,
    );
    const vao = gl.createVertexArray();
    const dataTexture = gl.createTexture();
    const lutTexture = gl.createTexture();
    if (!vao || !dataTexture || !lutTexture)
      throw new Error("Unable to allocate spectrogram resources");
    this.vao = vao;
    this.dataTexture = dataTexture;
    this.lutTexture = lutTexture;
    gl.bindTexture(gl.TEXTURE_2D, dataTexture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      gl.R8,
      this.points,
      this.rows,
      0,
      gl.RED,
      gl.UNSIGNED_BYTE,
      new Uint8Array(this.points * this.rows),
    );
    gl.bindTexture(gl.TEXTURE_2D, lutTexture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      gl.RGBA,
      256,
      1,
      0,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      turboLut(),
    );
  }
  addRow(row: Uint8Array) {
    this.addRows(row, 1, row.length);
  }
  addRows(
    values:Uint8Array,
    rowCount:number,
    pointCount:number,
    firstRowSequence=0,
    configurationGeneration?:number,
  ) {
    const gl = this.gl;
    if (
      rowCount <= 0 ||
      pointCount <= 0 ||
      values.length !== rowCount * pointCount
    )
      throw new Error("Waterfall batch dimensions do not match payload");
    if (rowCount > this.rows)
      throw new Error("Waterfall batch exceeds texture history depth");
    const transition=spectrogramStateTransition(
      this.configurationGeneration,
      this.points,
      configurationGeneration,
      pointCount,
    )
    if(transition.generationChanged&&configurationGeneration!==undefined){
      if(transition.resetHistory)this.cursor.reset()
      this.configurationGeneration=configurationGeneration
    }
    if (transition.reallocateTexture) {
      this.points = pointCount;
      this.cursor.reset();
      gl.bindTexture(gl.TEXTURE_2D, this.dataTexture);
      gl.texImage2D(
        gl.TEXTURE_2D,
        0,
        gl.R8,
        this.points,
        this.rows,
        0,
        gl.RED,
        gl.UNSIGNED_BYTE,
        new Uint8Array(this.points * this.rows),
      );
    }
    const uploadValues=this.debugRows?debugWaterfallRows(rowCount,pointCount,firstRowSequence):values
    gl.bindTexture(gl.TEXTURE_2D, this.dataTexture);
    const uploads=this.cursor.plan(rowCount)
    for (const upload of uploads) {
      const start = upload.sourceRowOffset * this.points;
      const end = start + upload.rowCount * this.points;
      gl.texSubImage2D(
        gl.TEXTURE_2D,
        0,
        0,
        upload.targetRow,
        this.points,
        upload.rowCount,
        gl.RED,
        gl.UNSIGNED_BYTE,
        uploadValues.subarray(start, end),
      );
    }
    this.cursor.commit(rowCount)
  }
  get textureRowCount() {
    return this.rows;
  }
  get pointCount(){
    return this.points
  }
  get wrapCount() {
    return this.cursor.wraps;
  }
  get validRowCount(){
    return this.cursor.validRows
  }
  get writeRow(){
    return this.cursor.writeRow
  }
  render(view: Viewport, requestedVisibleRows = this.rows) {
    const gl = this.gl;
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0.018,0.027,0.035,1)
    gl.clear(gl.COLOR_BUFFER_BIT)
    const plot=plotRectFramebuffer(Math.max(1,this.canvas.clientWidth),this.canvas.width)
    gl.viewport(plot.left,0,plot.width,this.canvas.height)
    gl.useProgram(this.program);
    gl.bindVertexArray(this.vao);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.dataTexture);
    gl.uniform1i(gl.getUniformLocation(this.program, "dataTex"), 0);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.lutTexture);
    gl.uniform1i(gl.getUniformLocation(this.program, "lut"), 1);
    const visibleRows = Math.max(
      1,
      Math.min(this.rows, Math.round(requestedVisibleRows)),
    );
    gl.uniform1f(
      gl.getUniformLocation(this.program, "head"),
      this.cursor.writeRow / this.rows,
    );
    gl.uniform1f(gl.getUniformLocation(this.program, "textureRows"), this.rows);
    gl.uniform1f(
      gl.getUniformLocation(this.program, "visibleRows"),
      visibleRows,
    );
    gl.uniform1f(gl.getUniformLocation(this.program,"validRows"),Math.min(visibleRows,this.cursor.validRows))
    gl.uniform1f(
      gl.getUniformLocation(this.program, "outputHeight"),
      this.canvas.height,
    );
    gl.uniform2f(
      gl.getUniformLocation(this.program, "view"),
      view.start,
      view.end,
    );
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  dispose() {
    const gl = this.gl;
    gl.deleteTexture(this.dataTexture);
    gl.deleteTexture(this.lutTexture);
    gl.deleteVertexArray(this.vao);
    gl.deleteProgram(this.program);
  }
}
