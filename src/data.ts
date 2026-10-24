import demo from './demo-data.json';
export const BASE='2026-10-24';
export const addDays=(date:string,days:number)=>{const d=new Date(date+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+days);return d.toISOString().slice(0,10)};
export const dateLabel=(date:string)=>date.slice(5).replace('-','.');
export const money=(n:number)=>'₩'+n.toLocaleString('ko-KR');
export interface Material {id:string;name:string;desc:string;stock:number;daily:number;unit:string;lot:string;expiry:string;storage:string;price:number;supplier:string;quality:'승인'|'검토 중';}
export const materials:Material[]=demo.materials as Material[];
export const suppliers=demo.suppliers;
export const plans=demo.plans;
export interface Order {id:string;material:string;supplier:string;quantity:number;cost:number;date:string;available:string;status:string;}
export const initialOrders:Order[]=demo.initialOrders;
export const stockDays=(m:Material)=>Math.floor(m.stock/m.daily);
export const depletion=(m:Material)=>addDays(BASE,stockDays(m));
export const risk=(m:Material)=>stockDays(m)<=7?'위험':stockDays(m)<=14?'주의':'안정';
export const totalInventory=materials.reduce((a,m)=>a+m.stock*m.price,0);
