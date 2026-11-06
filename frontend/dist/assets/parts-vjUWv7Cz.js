import{c as a,u as c,j as r,a as p,aF as u,N as g}from"./index-DmTMdNjV.js";import{B as h}from"./book-open-CITmanug.js";/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const f=a("ArrowDownLeft",[["path",{d:"M17 7 7 17",key:"15tmo1"}],["path",{d:"M17 17H7V7",key:"1org7z"}]]);/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const b=a("ArrowUpRight",[["path",{d:"M7 7h10v10",key:"1tivn9"}],["path",{d:"M7 17 17 7",key:"1vkiza"}]]);/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const y=a("Sprout",[["path",{d:"M7 20h10",key:"e6iznv"}],["path",{d:"M10 20c5.5-2.5.8-6.4 3-10",key:"161w41"}],["path",{d:"M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8z",key:"9gtqwd"}],["path",{d:"M14.1 6a7 7 0 0 0-1.1 4c1.9-.1 3.3-.6 4.3-1.4 1-1 1.6-2.3 1.7-4.6-2.7.1-4 1-4.9 2z",key:"bkxnd2"}]]);/**
 * @license lucide-react v0.460.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const v=a("Tag",[["path",{d:"M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z",key:"vktsd0"}],["circle",{cx:"7.5",cy:"7.5",r:".5",fill:"currentColor",key:"kqv944"}]]),l={production:r.jsx(y,{size:15}),exports:r.jsx(b,{size:15}),imports:r.jsx(f,{size:15}),prices:r.jsx(v,{size:14}),news:r.jsx(g,{size:14}),regulations:r.jsx(u,{size:14}),context:r.jsx(h,{size:14})},x=["production","exports","imports","prices","news","regulations","context"];function m(t,e){return t[e]?"yes":e==="exports"&&t.exports_mirror||e==="imports"&&t.imports_mirror?"mirror":"no"}function N({a:t,className:e,keys:s=x,size:o="md"}){const{t:d}=c();return r.jsx("div",{className:p("flex items-center",o==="sm"?"gap-px":"gap-1",e),children:s.map(n=>{const i=m(t,n);return r.jsx("span",{title:`${d(`countries.avail.${n}`)}: ${d(`countries.avail.${i==="yes"?"yes":i==="mirror"?"mirror":"no"}`)}`,className:p("inline-flex items-center justify-center rounded-sm border",o==="sm"?"h-[17px] w-[17px] [&>svg]:h-[12px] [&>svg]:w-[12px]":"h-[22px] w-[22px]",i==="yes"?"border-forest-100 bg-forest-50 text-forest-700":i==="mirror"?"border-dashed border-gold-light text-gold-dark":"border-transparent text-line"),children:l[n]},n)})})}function z({keys:t=["production","exports","imports","prices","news","regulations"]}){const{t:e}=c();return r.jsxs("div",{className:"flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.78rem] text-muted",children:[t.map(s=>r.jsxs("span",{className:"inline-flex items-center gap-1",children:[r.jsx("span",{className:"inline-flex h-[17px] w-[17px] items-center justify-center rounded-sm border border-forest-100 bg-forest-50 text-forest-700 [&>svg]:h-[12px] [&>svg]:w-[12px]",children:l[s]}),e(`countries.avail.${s}`)]},s)),r.jsxs("span",{className:"inline-flex items-center gap-1",children:[r.jsx("span",{className:"inline-block h-[15px] w-[15px] rounded-sm border border-dashed border-gold-light"}),e("countries.avail.mirror")]})]})}function A({a:t}){const{t:e}=c();return r.jsx("span",{className:"flex flex-wrap gap-1.5",children:x.map(s=>{const o=m(t,s);return r.jsxs("span",{title:e(`countries.avail.${o==="yes"?"yes":o==="mirror"?"mirror":"no"}`),className:p("inline-flex items-center gap-1.5 rounded-sm border px-2 py-[3px] text-[0.82rem]",o==="yes"?"border-forest-100 bg-forest-50 text-forest-800":o==="mirror"?"border-dashed border-gold-light bg-gold-pale/50 text-gold-dark":"border-line bg-white text-muted line-through decoration-muted/40"),children:[l[s],e(`countries.avail.${s}`)]},s)})})}function $(){const{t}=c();return e=>e?t(`countries.region.${e}`)===`countries.region.${e}`?e:t(`countries.region.${e}`):"—"}function M(t,e){return e==="it"?t.name_it:t.name_en}export{N as A,z as a,A as b,M as c,$ as u};
