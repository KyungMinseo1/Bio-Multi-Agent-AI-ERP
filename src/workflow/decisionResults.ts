export const costFields=[['actual_purchase_cost','실제 구매비'],['actual_transport_cost','실제 운송비'],['actual_testing_cost','실제 시험비'],['actual_storage_cost','실제 보관비'],['actual_disposal_cost','실제 폐기처리비']] as const;
export const quantityFields=[['used_quantity','실제 사용량'],['remaining_quantity','실제 잔량'],['expired_quantity','만료 폐기량'],['production_delay_days','생산 지연 일수']] as const;
export const displayResult=(value:unknown)=>value==null||value===''?'미확인':String(value);
export function outcomePayload(detail:Record<string,unknown>,values:Record<string,string>,receipts:Record<string,unknown>[],source:string){
 const payload:Record<string,unknown>={expected_revision:detail.revision,source_kind:source,receipts:receipts.map(r=>({line_id:r.line_id,actual_arrival:r.actual_arrival||null,usable_date:r.usable_date||null})),evaluation:values.evaluation||null,notes:values.notes||null,change_reason:values.change_reason,evidence_refs:(values.evidence_refs||'').split('\n').map(x=>x.trim()).filter(Boolean),production_delayed:!values.production_delayed?null:values.production_delayed==='true'};
 for(const [key] of [...costFields,...quantityFields])payload[key]=values[key]===''||values[key]==null?null:key.startsWith('actual_')?values[key]:Number(values[key]);
 return payload;
}
