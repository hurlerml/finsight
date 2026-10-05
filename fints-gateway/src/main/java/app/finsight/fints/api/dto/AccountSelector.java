package app.finsight.fints.api.dto;

import jakarta.validation.constraints.Size;

public record AccountSelector(
        @Size(max = 100) String externalId,
        @Size(max = 34) String iban
) {
}
