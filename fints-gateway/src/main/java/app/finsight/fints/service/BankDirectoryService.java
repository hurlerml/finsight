package app.finsight.fints.service;

import app.finsight.fints.api.BankController.BankResponse;
import org.kapott.hbci.manager.BankInfo;
import org.kapott.hbci.manager.HBCIUtils;
import org.springframework.stereotype.Service;

import java.text.Normalizer;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Map;

@Service
public class BankDirectoryService {
    private static final Map<String, String> BANK_ALIASES = Map.of(
            "DKB", "Deutsche Kreditbank",
            "ING", "ING-DiBa"
    );

    public List<BankResponse> search(String query, int limit) {
        String trimmed = query.trim();
        String lookup = BANK_ALIASES.getOrDefault(trimmed.toUpperCase(Locale.ROOT), trimmed);
        return HBCIUtils.searchBankInfo(lookup).stream()
                .filter(bank -> bank.getPinTanAddress() != null && !bank.getPinTanAddress().isBlank())
                .filter(bank -> matchScore(bank, lookup) < 10)
                .sorted(Comparator.comparingInt(bank -> matchScore(bank, lookup)))
                .limit(limit)
                .map(BankDirectoryService::map)
                .toList();
    }

    private static BankResponse map(BankInfo bank) {
        return new BankResponse(
                bank.getBlz(),
                bank.getBic(),
                bank.getName(),
                bank.getLocation(),
                bank.getPinTanAddress(),
                bank.getPinTanVersion() == null ? null : bank.getPinTanVersion().getId()
        );
    }

    private static int matchScore(BankInfo bank, String query) {
        String needle = normalize(query);
        String name = normalize(bank.getName());
        String blz = normalize(bank.getBlz());
        String bic = normalize(bank.getBic());
        if (needle.equals(blz) || needle.equals(bic) || needle.equals(name)) {
            return 0;
        }
        if (blz.startsWith(needle) || bic.startsWith(needle)) {
            return 1;
        }
        List<String> tokens = List.of(name.split("[^a-z0-9]+"));
        if (tokens.contains(needle)) {
            return 2;
        }
        if (name.startsWith(needle)) {
            return 3;
        }
        if (tokens.stream().anyMatch(token -> token.startsWith(needle))) {
            return 4;
        }
        return name.contains(needle) ? 5 : 10;
    }

    private static String normalize(String value) {
        if (value == null) {
            return "";
        }
        return Normalizer.normalize(value, Normalizer.Form.NFKD)
                .replaceAll("\\p{M}", "")
                .toLowerCase(Locale.ROOT)
                .trim();
    }
}
