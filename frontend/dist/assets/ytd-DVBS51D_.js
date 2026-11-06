import{c}from"./index-DmTMdNjV.js";/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const s=c("CircleSlash",[["circle",{cx:"12",cy:"12",r:"10",key:"1mglay"}],["line",{x1:"9",x2:"15",y1:"15",y2:"9",key:"1dfufj"}]]),o={it:["gen","feb","mar","apr","mag","giu","lug","ago","set","ott","nov","dic"],en:["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]},i={it:["gennaio","febbraio","marzo","aprile","maggio","giugno","luglio","agosto","settembre","ottobre","novembre","dicembre"],en:["January","February","March","April","May","June","July","August","September","October","November","December"]};function u(e,r,n){const t=o[n][e-1]??String(e),a=o[n][r-1]??String(r);return e===r?t:`${t}–${a}`}function m(e,r){const n=e?/^(\d{4})-(\d{2})$/.exec(e):null;return n?`${i[r][Number(n[2])-1]} ${n[1]}`:e??"—"}function b(e,r){return`${u(e.month_from,e.month_to,r)} ${e.prev_year}`}export{s as C,m as a,u as f,b as p};
