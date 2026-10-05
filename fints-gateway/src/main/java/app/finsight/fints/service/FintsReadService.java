package app.finsight.fints.service;

import app.finsight.fints.api.dto.AccountResponse;
import app.finsight.fints.api.dto.AccountSelector;
import app.finsight.fints.api.dto.AccountsResult;
import app.finsight.fints.api.dto.BalanceResponse;
import app.finsight.fints.api.dto.BalanceResult;
import app.finsight.fints.api.dto.FintsCredentials;
import app.finsight.fints.api.dto.FintsJobRequest;
import app.finsight.fints.api.dto.TransactionResponse;
import app.finsight.fints.api.dto.TransactionsResult;
import app.finsight.fints.hbci.GatewayHbciCallback;
import app.finsight.fints.job.GatewayJob;
import app.finsight.fints.job.JobStatus;
import org.kapott.hbci.GV.HBCIJob;
import org.kapott.hbci.GV.parsers.ISEPAParser;
import org.kapott.hbci.GV.parsers.SEPAParserFactory;
import org.kapott.hbci.GV_Result.GVRKUms;
import org.kapott.hbci.GV_Result.GVRSaldoReq;
import org.kapott.hbci.manager.BankInfo;
import org.kapott.hbci.manager.HBCIHandler;
import org.kapott.hbci.manager.HBCIUtils;
import org.kapott.hbci.manager.HBCIVersion;
import org.kapott.hbci.passport.HBCIPassportPinTanMemory;
import org.kapott.hbci.sepa.SepaVersion;
import org.kapott.hbci.status.HBCIExecStatus;
import org.kapott.hbci.structures.Konto;
import org.kapott.hbci.structures.Value;
import org.springframework.stereotype.Service;

import java.io.ByteArrayInputStream;
import java.math.BigDecimal;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;

@Service
public class FintsReadService {
    private static final String PRODUCT_VERSION = applicationVersion();

    private final GatewayHbciCallback callback;

    public FintsReadService(GatewayHbciCallback callback) {
        this.callback = callback;
    }

    private static String applicationVersion() {
        String version = FintsReadService.class.getPackage().getImplementationVersion();
        return version == null || version.isBlank() ? "development" : version;
    }

    public Object execute(FintsJobRequest request, GatewayJob job) throws Exception {
        validateEndpoint(request.credentials().endpoint());
        return callback.withContext(request.credentials(), job, () -> executeWithContext(request, job));
    }

    private Object executeWithContext(FintsJobRequest request, GatewayJob gatewayJob) {
        FintsCredentials credentials = request.credentials();
        HBCIUtils.setParam("client.product.name", credentials.productId());
        HBCIUtils.setParam("client.product.version", PRODUCT_VERSION);

        HBCIPassportPinTanMemory passport = null;
        HBCIHandler handler = null;
        try {
            passport = createPassport(credentials);
            handler = new HBCIHandler(hbciVersion(credentials.blz()), passport);
            gatewayJob.update(JobStatus.RUNNING, "Reading bank data");

            return switch (request.operation()) {
                case ACCOUNTS -> readAccounts(passport);
                case TRANSACTIONS -> readTransactions(
                        handler,
                        passport,
                        request.account(),
                        request.since(),
                        request.until()
                );
                case BALANCE -> readBalance(handler, passport, request.account());
            };
        } finally {
            if (handler != null) {
                handler.close();
            }
            if (passport != null) {
                passport.clearPIN();
                passport.close();
            }
        }
    }

    private static HBCIPassportPinTanMemory createPassport(FintsCredentials credentials) {
        HBCIPassportPinTanMemory passport = new HBCIPassportPinTanMemory(null);
        passport.setCountry("DE");
        passport.setBLZ(credentials.blz());
        passport.setHost(credentials.endpoint());
        passport.setPort(443);
        passport.setFilterType("Base64");
        passport.setUserId(credentials.user());
        passport.setCustomerId(isBlank(credentials.customerId())
                ? credentials.user()
                : credentials.customerId());
        passport.setPIN(credentials.pin());
        return passport;
    }

    private static String hbciVersion(String blz) {
        BankInfo bank = HBCIUtils.getBankInfo(blz);
        HBCIVersion version = bank == null ? null : bank.getPinTanVersion();
        return version == null ? HBCIVersion.HBCI_300.getId() : version.getId();
    }

    private static AccountsResult readAccounts(HBCIPassportPinTanMemory passport) {
        Konto[] accounts = passport.getAccounts();
        List<AccountResponse> mapped = new ArrayList<>();
        if (accounts != null) {
            for (Konto account : accounts) {
                mapped.add(mapAccount(account));
            }
        }
        return new AccountsResult(mapped);
    }

    private static TransactionsResult readTransactions(
            HBCIHandler handler,
            HBCIPassportPinTanMemory passport,
            AccountSelector selector,
            LocalDate since,
            LocalDate until
    ) {
        Konto account = findAccount(passport, selector);
        HBCIJob<?> transactionJob = transactionJob(handler, account, since, until);
        HBCIJob<?> balanceJob = handler.isSupported("SaldoReq")
                ? createBalanceJob(handler, account)
                : null;

        HBCIExecStatus status = handler.execute();
        GVRKUms transactionResult = (GVRKUms) transactionJob.getJobResult();
        if (transactionResult == null || !transactionResult.isOK()) {
            throw new IllegalStateException(errorMessage(
                    "The bank rejected the transaction request",
                    transactionResult == null ? status.getErrorString() : transactionResult.toString()
            ));
        }

        List<TransactionResponse> transactions = new ArrayList<>();
        for (GVRKUms.UmsLine line : bookedLines(transactionResult)) {
            transactions.add(mapTransaction(line, false));
        }
        for (GVRKUms.UmsLine line : pendingLines(transactionResult)) {
            transactions.add(mapTransaction(line, true));
        }

        BalanceResponse balance = null;
        if (balanceJob != null) {
            GVRSaldoReq balanceResult = (GVRSaldoReq) balanceJob.getJobResult();
            if (balanceResult != null && balanceResult.isOK()) {
                balance = mapBalance(balanceResult, account);
            }
        }
        return new TransactionsResult(transactions, balance);
    }

    private static BalanceResult readBalance(
            HBCIHandler handler,
            HBCIPassportPinTanMemory passport,
            AccountSelector selector
    ) {
        Konto account = findAccount(passport, selector);
        HBCIJob<?> job = createBalanceJob(handler, account);
        HBCIExecStatus status = handler.execute();
        GVRSaldoReq result = (GVRSaldoReq) job.getJobResult();
        if (result == null || !result.isOK()) {
            throw new IllegalStateException(errorMessage(
                    "The bank rejected the balance request",
                    result == null ? status.getErrorString() : result.toString()
            ));
        }
        return new BalanceResult(mapBalance(result, account));
    }

    private static HBCIJob<?> transactionJob(
            HBCIHandler handler,
            Konto account,
            LocalDate since,
            LocalDate until
    ) {
        String jobName = handler.isSupported("KUmsAllCamt") ? "KUmsAllCamt" : "KUmsAll";
        HBCIJob<?> job = handler.newJob(jobName);
        job.setParam("my", account);
        job.setParam("startdate", asDate(since));
        job.setParam("enddate", asDate(until));
        job.addToQueue();
        return job;
    }

    private static HBCIJob<?> createBalanceJob(HBCIHandler handler, Konto account) {
        HBCIJob<?> job = handler.newJob("SaldoReq");
        job.setParam("my", account);
        job.addToQueue();
        return job;
    }

    private static AccountResponse mapAccount(Konto account) {
        String externalId = firstNonBlank(account.iban, account.number);
        String type = firstNonBlank(account.type, account.acctype);
        String name = accountName(type);
        return new AccountResponse(
                externalId,
                blankToNull(account.iban),
                blankToNull(account.bic),
                blankToNull(account.number),
                blankToNull(account.subnumber),
                name,
                firstNonBlank(account.curr, "EUR"),
                isCard(type) ? "card" : "checking"
        );
    }

    private static String accountName(String type) {
        if (isCard(type)) {
            return "Karte";
        }
        if (!isBlank(type) && !type.matches("\\d+")) {
            return type.trim();
        }
        return "Girokonto";
    }

    private static boolean isCard(String value) {
        String normalized = value == null ? "" : value.toLowerCase(Locale.ROOT);
        return normalized.contains("kredit") || normalized.contains("credit")
                || normalized.contains("mastercard") || normalized.contains("visa")
                || normalized.contains("karte") || normalized.contains("card");
    }

    private static Konto findAccount(HBCIPassportPinTanMemory passport, AccountSelector selector) {
        String externalId = normalizeAccountId(selector.externalId());
        String iban = normalizeAccountId(selector.iban());
        Konto[] accounts = passport.getAccounts();
        if (accounts != null) {
            for (Konto account : accounts) {
                if ((!externalId.isEmpty() && externalId.equals(normalizeAccountId(
                        firstNonBlank(account.iban, account.number)
                ))) || (!iban.isEmpty() && iban.equals(normalizeAccountId(account.iban)))) {
                    return account;
                }
            }
        }
        throw new IllegalArgumentException("The requested account was not returned by the bank");
    }

    private static TransactionResponse mapTransaction(GVRKUms.UmsLine line, boolean pending) {
        Value value = line.value;
        BigDecimal amount = value == null ? BigDecimal.ZERO : value.getBigDecimalValue();
        String currency = value == null ? "EUR" : firstNonBlank(value.getCurr(), "EUR");
        String counterparty = line.other == null
                ? null
                : joinNonBlank(" ", line.other.name, line.other.name2);
        String purpose = line.usage == null ? "" : joinNonBlank(" ", line.usage.toArray(String[]::new));
        Map<String, String> metadata = new LinkedHashMap<>();
        putIfPresent(metadata, "institutionReference", line.instref);
        putIfPresent(metadata, "customerReference", line.customerref);
        putIfPresent(metadata, "endToEndId", line.endToEndId);
        putIfPresent(metadata, "transactionId", line.id);
        putIfPresent(metadata, "transactionCode", line.gvcode);
        putIfPresent(metadata, "purposeCode", line.purposecode);
        putIfPresent(metadata, "mandateId", line.mandateId);
        putIfPresent(metadata, "additional", line.additional);

        return new TransactionResponse(
                firstMeaningfulReference(line.instref, line.endToEndId, line.customerref, line.id),
                asLocalDate(line.bdate == null ? line.valuta : line.bdate),
                asLocalDate(line.valuta),
                amount,
                currency,
                blankToNull(counterparty),
                purpose,
                firstNonBlank(line.text, line.additional),
                pending,
                metadata
        );
    }

    private static BalanceResponse mapBalance(GVRSaldoReq result, Konto account) {
        GVRSaldoReq.Info[] entries = result.getEntries();
        if (entries == null || entries.length == 0 || entries[0].ready == null
                || entries[0].ready.value == null) {
            return null;
        }
        GVRSaldoReq.Info entry = entries[0];
        Value booked = entry.ready.value;
        Value available = entry.available;
        return new BalanceResponse(
                booked.getBigDecimalValue(),
                available == null ? null : available.getBigDecimalValue(),
                firstNonBlank(booked.getCurr(), account.curr, "EUR"),
                Instant.now()
        );
    }

    private static List<GVRKUms.UmsLine> bookedLines(GVRKUms result) {
        List<GVRKUms.UmsLine> lines = result.getFlatData();
        if (!lines.isEmpty() || result.camtBooked == null || result.camtBooked.isEmpty()) {
            return lines;
        }
        return parseCamt(result.camtBooked);
    }

    private static List<GVRKUms.UmsLine> pendingLines(GVRKUms result) {
        List<GVRKUms.UmsLine> lines = result.getFlatDataUnbooked();
        if (!lines.isEmpty() || result.camtNotBooked == null || result.camtNotBooked.isEmpty()) {
            return lines;
        }
        return parseCamt(result.camtNotBooked);
    }

    @SuppressWarnings("unchecked")
    private static List<GVRKUms.UmsLine> parseCamt(List<String> documents) {
        List<GVRKUms.UmsLine> lines = new ArrayList<>();
        for (String document : documents) {
            byte[] xml = document.getBytes(StandardCharsets.UTF_8);
            SepaVersion version = SepaVersion.autodetect(new ByteArrayInputStream(xml));
            ISEPAParser<List<GVRKUms.BTag>> parser =
                    (ISEPAParser<List<GVRKUms.BTag>>) SEPAParserFactory.get(version);
            List<GVRKUms.BTag> days = new ArrayList<>();
            parser.parse(new ByteArrayInputStream(xml), days);
            for (GVRKUms.BTag day : days) {
                if (day.lines != null) {
                    lines.addAll(day.lines);
                }
            }
        }
        return lines;
    }

    static void validateEndpoint(String endpoint) {
        URI uri;
        try {
            uri = URI.create(endpoint);
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Invalid FinTS endpoint", exception);
        }
        if (!"https".equalsIgnoreCase(uri.getScheme()) || isBlank(uri.getHost())
                || uri.getUserInfo() != null || (uri.getPort() != -1 && uri.getPort() != 443)) {
            throw new IllegalArgumentException("FinTS endpoint must be an HTTPS URL on port 443");
        }
    }

    private static Date asDate(LocalDate date) {
        return Date.from(date.atStartOfDay(ZoneId.systemDefault()).toInstant());
    }

    private static LocalDate asLocalDate(Date date) {
        return date == null ? null : date.toInstant().atZone(ZoneId.systemDefault()).toLocalDate();
    }

    private static String normalizeAccountId(String value) {
        return value == null ? "" : value.replace(" ", "").toUpperCase(Locale.ROOT);
    }

    private static String firstMeaningfulReference(String... candidates) {
        for (String candidate : candidates) {
            if (!isBlank(candidate)) {
                String normalized = candidate.trim();
                if (!List.of("NOTPROVIDED", "NONREF", "NONE", "-")
                        .contains(normalized.toUpperCase(Locale.ROOT))) {
                    return normalized;
                }
            }
        }
        return null;
    }

    private static String firstNonBlank(String... values) {
        for (String value : values) {
            if (!isBlank(value)) {
                return value.trim();
            }
        }
        return "";
    }

    private static String joinNonBlank(String delimiter, String... values) {
        return String.join(delimiter, java.util.Arrays.stream(values)
                .filter(Objects::nonNull)
                .map(String::trim)
                .filter(value -> !value.isEmpty())
                .toList());
    }

    private static void putIfPresent(Map<String, String> target, String key, String value) {
        if (!isBlank(value)) {
            target.put(key, value);
        }
    }

    private static String errorMessage(String fallback, String details) {
        if (isBlank(details)) {
            return fallback;
        }
        String normalized = details.replaceAll("[\\r\\n]+", " ").trim();
        return fallback + ": " + normalized.substring(0, Math.min(normalized.length(), 500));
    }

    private static String blankToNull(String value) {
        return isBlank(value) ? null : value.trim();
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
