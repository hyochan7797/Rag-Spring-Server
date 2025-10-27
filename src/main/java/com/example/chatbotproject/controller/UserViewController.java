package com.example.chatbotproject.controller;


import org.springframework.stereotype.Controller;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.servlet.mvc.support.RedirectAttributes;

@Controller
public class UserViewController {

    @GetMapping("/login")
    public String login(@RequestParam(value = "error", required = false) String error, RedirectAttributes redirectAttributes) {
        if (error != null) {
            redirectAttributes.addFlashAttribute("loginError", true);
            return "redirect:/login"; // 에러가 있으면 리다이렉트하여 URL에서 error 제거
        }
        return "login";
    }
    


    @GetMapping("/signup")
    public String signup() {
        return "signup";
    }
    @GetMapping("/chat")
    public String chat() {
        return "chat"; //
    }
}
