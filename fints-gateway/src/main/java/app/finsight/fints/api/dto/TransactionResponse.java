package app.finsight.fints.api.dto;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Map;

public record TransactionResponse(
        String externalId,
        LocalDate bookingDate,
        LocalDate valueDate,
        BigDecimal amount,
        String currency,
        String counterparty,
        String purpose,
        String bookingText,
        boolean pending,
        Map<String, String> metadata
) {
}
