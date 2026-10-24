import {it,expect,vi} from 'vitest';
const mocks=vi.hoisted(()=>({api:vi.fn(),send:vi.fn()}));
vi.mock('./vendor/api',()=>({...mocks,record:(x:unknown)=>x}));

it('작성 화면의 조회가 로컬 초안의 충돌 검사용 버전을 올려 쓰지 않는다',async()=>{
 vi.resetModules();
 const connection=await import('./connection');
 mocks.api.mockResolvedValueOnce({revision:3}).mockResolvedValueOnce({revision:4});
 await connection.getWorkspace();
 await connection.peekWorkspace();
 mocks.send.mockRejectedValueOnce(Error('workspace_conflict'));
 await expect(connection.saveWorkspace({} as never)).rejects.toThrow('workspace_conflict');
 expect(mocks.send).toHaveBeenCalledWith('/workspace',{workflow:{},expected_revision:3,migration:false},'PUT');
});
