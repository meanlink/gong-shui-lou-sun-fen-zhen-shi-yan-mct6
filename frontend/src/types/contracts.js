/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{id:?number,job_id:number,status:'pending'|'running'|'passed'|'failed'|'unverifiable',progress:number,attempts:number,rule_version:string,evidence_hash:string,has_evidence:boolean,seal_intact:boolean,differences:Array<{type:string,message?:string,label?:string,segment_id?:string,field?:string,expected:*,actual:*}>}} Verification */
export {};
