package com.example.chatbotproject.batch;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.batch.core.StepContribution;
import org.springframework.batch.core.scope.context.ChunkContext;
import org.springframework.batch.core.step.tasklet.Tasklet;
import org.springframework.batch.repeat.RepeatStatus;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

@Slf4j
@Component
@RequiredArgsConstructor
public class FssRefreshTasklet implements Tasklet {

    private final RestTemplate fastApiAdminRestTemplate;

    @Value("${fastapi.admin.url}")
    private String fastApiAdminUrl;

    @Value("${ADMIN_API_KEY:}")
    private String adminApiKey;

    @Override
    public RepeatStatus execute(StepContribution contribution, ChunkContext chunkContext) {
        log.info("[Batch] FSS refresh request started. url={}", fastApiAdminUrl);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-Admin-Key", adminApiKey);
        headers.set("ngrok-skip-browser-warning", "true");

        try {
            ResponseEntity<Map> response = fastApiAdminRestTemplate.postForEntity(
                    fastApiAdminUrl, new HttpEntity<>(headers), Map.class
            );

            @SuppressWarnings("unchecked")
            Map<String, Object> body = (Map<String, Object>) response.getBody();
            if (body == null || !"ok".equals(body.get("status"))) {
                String msg = body != null ? String.valueOf(body.get("message")) : "empty response";
                throw new RuntimeException("FSS refresh failed: " + msg);
            }

            Object chunksRaw = body.get("chunks");
            int chunks = chunksRaw instanceof Number ? ((Number) chunksRaw).intValue() : 0;
            log.info("[Batch] FSS refresh completed. chunks={}", chunks);

        } catch (RestClientException e) {
            throw new RuntimeException("[Batch] FastAPI refresh call failed: " + e.getMessage(), e);
        }

        return RepeatStatus.FINISHED;
    }
}
