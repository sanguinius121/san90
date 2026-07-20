export const FIXED_RENDER_FPS=60
export const FIXED_RENDER_PERIOD_MS=1000/FIXED_RENDER_FPS

export interface FixedRenderDecision{due:boolean;nextDeadline:number}

export function fixedRenderDecision(now:number,nextDeadline:number):FixedRenderDecision{
  if(nextDeadline===0)return{due:true,nextDeadline:now+FIXED_RENDER_PERIOD_MS}
  if(now<nextDeadline)return{due:false,nextDeadline}
  const elapsedPeriods=Math.floor((now-nextDeadline)/FIXED_RENDER_PERIOD_MS)+1
  return{due:true,nextDeadline:nextDeadline+elapsedPeriods*FIXED_RENDER_PERIOD_MS}
}
