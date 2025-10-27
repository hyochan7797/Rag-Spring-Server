package com.example.chatbotproject.service;



import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.*;

@Service
public class RagService {

    public String askQuestionToRag(String question) {
        String url = "http://localhost:8000/chat";

        RestTemplate restTemplate = new RestTemplate();

        // 요청 헤더
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);

        // 요청 바디
        Map<String, String> body = new HashMap<>();
        body.put("question", question);

        HttpEntity<Map<String, String>> request = new HttpEntity<>(body, headers);

        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(url, request, Map.class);
            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                return response.getBody().get("answer").toString();
            } else {
                return "FastAPI 응답 실패";
            }
        } catch (Exception e) {
            return "FastAPI 서버 호출 중 오류 발생: " + e.getMessage();
        }
    }
}