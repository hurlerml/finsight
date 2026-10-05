package app.finsight.fints.api.dto;

public record AccountResponse(
        String externalId,
        String iban,
        String bic,
        String accountNumber,
        String subaccountNumber,
        String name,
        String currency,
        String accountType
) {
}
