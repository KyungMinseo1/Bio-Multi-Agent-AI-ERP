import {build} from 'esbuild';
await build({entryPoints:['scripts/workflow-runner.ts'],bundle:true,platform:'node',format:'cjs',outfile:'server-dist/workflow.cjs',target:'node22'});
