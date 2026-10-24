import type {Workflow} from '../workflow/engine';
import {api,send,record} from './vendor/api';
export interface RemoteWorkspace {revision:number;workflow:Workflow|null;stamp?:string;scenario_id:string;}
let revision:number|undefined;
export const isServerEnabled=()=>sessionStorage.getItem('bioflow-server-enabled')==='1';
export function setServerEnabled(value:boolean){sessionStorage.setItem('bioflow-server-enabled',value?'1':'0');}
export async function getWorkspace(){const value=await api('/workspace') as RemoteWorkspace;revision=value.revision;return value;}
export async function saveWorkspace(workflow:Workflow,migration=false){if(revision===undefined)await getWorkspace();const result=await send('/workspace',{workflow,expected_revision:revision,migration},'PUT') as RemoteWorkspace;revision=result.revision;return result;}
export async function serverCommand(command:string,args:Record<string,unknown>={}){if(revision===undefined)await getWorkspace();const value=await send('/workspace/commands',{command,args,expected_revision:revision}) as RemoteWorkspace;revision=value.revision;return value;}
export async function adoptReview(recommendationId:string,stamp:string){const result=await send('/workspace/adopt-review',{recommendation_id:recommendationId,stamp,expected_revision:revision}) as RemoteWorkspace;revision=result.revision;return result;}
export async function loginLocal(){const result=record(await send('/auth/local-demo',{}));await getWorkspace();setServerEnabled(true);return record(result.user);}
