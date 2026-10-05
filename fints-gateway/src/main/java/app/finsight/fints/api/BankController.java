package app.finsight.fints.api;

import app.finsight.fints.service.BankDirectoryService;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Size;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@Validated
public class BankController {
    private final BankDirectoryService bankDirectory;

    public BankController(BankDirectoryService bankDirectory) {
        this.bankDirectory = bankDirectory;
    }

    @GetMapping("/health")
    public HealthResponse health() {
        return new HealthResponse("ok");
    }

    @GetMapping("/banks")
    public BankSearchResponse banks(
            @RequestParam @Size(min = 3, max = 120) String query,
            @RequestParam(defaultValue = "20") @Min(1) @Max(50) int limit
    ) {
        List<BankResponse> items = bankDirectory.search(query, limit);
        return new BankSearchResponse(items, items.size());
    }

    public record HealthResponse(String status) {
    }

    public record BankSearchResponse(List<BankResponse> items, int count) {
    }

    public record BankResponse(
            String blz,
            String bic,
            String name,
            String location,
            String pinTanAddress,
            String pinTanVersion
    ) {
    }
}
