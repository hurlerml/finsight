package app.finsight.fints.api.dto;

import java.math.BigDecimal;
import java.time.Instant;

public record BalanceResponse(
        BigDecimal booked,
        BigDecimal available,
        String currency,
        Instant capturedAt
) {
}
