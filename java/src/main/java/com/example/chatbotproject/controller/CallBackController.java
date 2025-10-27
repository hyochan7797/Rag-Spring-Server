package com.example.chatbotproject.controller;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
public class CallBackController {

    @PostMapping("/callback")
    public String handleCallback(@RequestBody String responseData) {
        System.out.println("💡 API Callback Received: " + responseData);
        return "Callback received successfully!";
    }
}
