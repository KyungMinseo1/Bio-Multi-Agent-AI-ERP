import type {ErpData} from '../erp/model';
export function normalizeSupplierEmails(data:ErpData):ErpData {return {...data,vendors:data.vendors.map(v=>{const {quoteEmail,...rest}=v as typeof v&{quoteEmail?:string};return {...rest,email:rest.email??quoteEmail??''}})};}
export function supplierEmailError(address:string,live=false){
 if(!/^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$/.test(address)||address.includes('..')||address.startsWith('.'))return '업체 담당자 이메일이 없거나 형식이 잘못됐습니다. 주소를 수정하고 업체 이메일 저장을 누르세요.';
 if(live&&/@(?:.*\.)?(?:example\.(?:com|net|org)|test|invalid|localhost)$/i.test(address))return '예시 주소로 실제 발송할 수 없습니다. 업체 이메일을 수정하거나 별도 허용 테스트 수신자를 설정하세요.';
 return '';
}
