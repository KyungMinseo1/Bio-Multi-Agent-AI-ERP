import {seedWorkflow,type Workflow} from './engine';
import {validate,load as loadPrevious} from '../erp/store';
const KEY='bioflow-workflow-21';
export function loadFlow():Workflow{try{const x=JSON.parse(localStorage.getItem(KEY)||'null');if(x?.schema===21&&!validate(x.data).length&&Array.isArray(x.approvals)&&Array.isArray(x.inquiries)&&Array.isArray(x.audit))return x;}catch{/* Invalid storage is not applied. */}return seedWorkflow(loadPrevious().data);}
export function saveFlow(s:Workflow){try{localStorage.setItem(KEY,JSON.stringify({...s,reports:s.reports.slice(0,12),audit:s.audit.slice(0,400),notifications:s.notifications.slice(0,100)}));return true;}catch{return false;}}
