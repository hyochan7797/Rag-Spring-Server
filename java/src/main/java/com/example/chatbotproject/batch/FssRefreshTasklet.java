package com.example.chatbotproject.batch;

import lombok.extern.slf4j.Slf4j;
import org.springframework.batch.core.StepContribution;
import org.springframework.batch.core.scope.context.ChunkContext;
import org.springframework.batch.core.step.tasklet.Tasklet;
import org.springframework.batch.repeat.RepeatStatus;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

@Slf4j
@Component
public class FssRefreshTasklet implements Tasklet {

    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${fastapi.admin.url}")
    private String fastApiAdminUrl;

    @Value("${ADMIN_API_KEY:}")
    private String adminApiKey;

    @Override
    public RepeatStatus execute(StepContribution contribution, ChunkContext chunkContext) {
        log.info("[Batch] FSS 데이터 갱신 요청 → {}", fastApiAdminUrl);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-Admin-Key", adminApiKey);

        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                    fastApiAdminUrl, new HttpEntity<>(headers), Map.class
            );

            @SuppressWarnings("unchecked")
            Map<String, Object> body = (Map<String, Object>) response.getBody();
            if (body == null || !"ok".equals(body.get("status"))) {
                String msg = body != null ? String.valueOf(body.get("message")) : "응답 없음";
                throw new RuntimeException("FSS 갱신 실패: " + msg);
            }

            Object chunksRaw = body.get("chunks");
            int chunks = chunksRaw instanceof Number ? ((Number) chunksRaw).intValue() : 0;
            log.info("[Batch] FSS 갱신 완료 — {}개 청크 적재", chunks);

        } catch (RestClientException e) {
            // FastAPI 연결 실패 시 배치 스텝 실패로 처리 → Spring Batch가 재시도
            throw new RuntimeException("[Batch] FastAPI 호출 실패: " + e.getMessage(), e);
        }

        return RepeatStatus.FINISHED;
    }
}
