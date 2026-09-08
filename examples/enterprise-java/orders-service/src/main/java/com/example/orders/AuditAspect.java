package com.example.orders;

import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.stereotype.Component;

@Aspect
@Component
public class AuditAspect {

    @Around("execution(* com.example.orders.OrderService.*(..))")
    public Object audit(ProceedingJoinPoint pjp) throws Throwable {
        return pjp.proceed();
    }
}
