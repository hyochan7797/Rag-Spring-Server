package com.example.chatbotproject.batch;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.batch.core.Job;
import org.springframework.batch.core.JobExecution;
import org.springframework.batch.core.JobParameters;
import org.springframework.batch.core.JobParametersBuilder;
import org.springframework.batch.core.launch.JobLauncher;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class LoanDataRefreshScheduler {

    private final JobLauncher jobLauncher;
    private final Job loanDataRefreshJob;

    // application.yml의 loan-refresh.cron 값 사용, 기본값: 매일 새벽 2시
    @Scheduled(cron = "${loan-refresh.cron:0 0 2 * * *}")
    public void scheduledRefresh() {
        log.info("[Scheduler] 정기 FSS 데이터 갱신 시작");
        run("scheduled");
    }

    public JobExecution run(String triggeredBy) {
        try {
            JobParameters params = new JobParametersBuilder()
                    .addLong("timestamp", System.currentTimeMillis())  // 매 실행마다 새 인스턴스
                    .addString("triggeredBy", triggeredBy)
                    .toJobParameters();

            JobExecution execution = jobLauncher.run(loanDataRefreshJob, params);
            log.info("[Scheduler] 배치 완료 — status={}, triggeredBy={}", execution.getStatus(), triggeredBy);
            return execution;

        } catch (Exception e) {
            log.error("[Scheduler] 배치 실행 실패: {}", e.getMessage(), e);
            throw new RuntimeException("배치 실행 실패", e);
        }
    }
}
