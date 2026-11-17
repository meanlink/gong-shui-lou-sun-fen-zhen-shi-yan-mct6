export const Role={admin:'业务负责人',analyst:'分析员',viewer:'观察员'};
export const JobStatus={queued:'排队中',running:'计算中',completed:'已完成',failed:'执行失败'};
export const VerificationStatus={pending:'待核验',running:'复算中',passed:'验真通过',failed:'验真失败',unverifiable:'不可验真'};
export const DiffType={metric_mismatch:'指标不一致',metric_missing:'指标缺件',metric_extra:'多出指标',segment_mismatch:'逐段分诊不一致',segment_missing:'管段缺件',segment_extra:'多出管段',result_mismatch:'结论不一致',fingerprint_mismatch:'成果指纹不一致',seal_tampered:'封存被改动',missing_evidence:'历史缺依据',failed_reason:'失败原因',truncated:'差异已截断'};
