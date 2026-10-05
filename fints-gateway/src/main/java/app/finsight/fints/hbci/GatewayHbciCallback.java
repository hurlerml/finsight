package app.finsight.fints.hbci;

import app.finsight.fints.api.dto.FintsCredentials;
import app.finsight.fints.job.GatewayJob;
import app.finsight.fints.job.JobStatus;
import app.finsight.fints.job.UnsupportedTanException;
import org.kapott.hbci.callback.AbstractHBCICallback;
import org.kapott.hbci.passport.HBCIPassport;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.Callable;

@Component
public class GatewayHbciCallback extends AbstractHBCICallback {
    private final ThreadLocal<ExecutionContext> active = new ThreadLocal<>();

    public <T> T withContext(FintsCredentials credentials, GatewayJob job, Callable<T> operation)
            throws Exception {
        active.set(new ExecutionContext(credentials, job));
        try {
            return operation.call();
        } finally {
            active.remove();
        }
    }

    @Override
    public void log(String message, int level, Date date, StackTraceElement trace) {
        // HBCI4Java may include bank payload data in verbose logs. The gateway
        // deliberately keeps library logging disabled outside explicit local debugging.
    }

    @Override
    public void callback(
            HBCIPassport passport,
            int reason,
            String message,
            int dataType,
            StringBuffer response
    ) {
        ExecutionContext context = requireContext();
        FintsCredentials credentials = context.credentials();

        switch (reason) {
            case NEED_COUNTRY -> replace(response, "DE");
            case NEED_BLZ -> replace(response, credentials.blz());
            case NEED_HOST -> replace(response, credentials.endpoint());
            case NEED_PORT -> replace(response, "443");
            case NEED_FILTER -> replace(response, "Base64");
            case NEED_USERID -> replace(response, credentials.user());
            case NEED_CUSTOMERID -> replace(
                    response,
                    isBlank(credentials.customerId()) ? credentials.user() : credentials.customerId()
            );
            case NEED_PT_PIN, NEED_PASSPHRASE_LOAD, NEED_PASSPHRASE_SAVE ->
                    replace(response, credentials.pin());
            case NEED_PT_SECMECH -> replace(
                    response,
                    selectTanMechanism(response.toString(), credentials.tanMechanism())
            );
            case NEED_PT_TANMEDIA -> replace(
                    response,
                    selectTanMedium(response.toString(), credentials.tanMedium())
            );
            case NEED_PT_DECOUPLED, NEED_PT_DECOUPLED_RETRY -> context.job().update(
                    JobStatus.AWAITING_USER_ACTION,
                    isBlank(message) ? "Approve the request in your banking app" : message
            );
            case NEED_PT_TAN, NEED_PT_PHOTOTAN, NEED_PT_QRTAN -> throw new UnsupportedTanException(
                    "This bank requires a TAN to be entered. The first HBCI4Java integration " +
                            "supports decoupled app approval; typed, photo and QR TAN input " +
                            "will be added to the account setup flow."
            );
            case NEED_NEW_INST_KEYS_ACK, NEED_INFOPOINT_ACK, HAVE_VOP_RESULT ->
                    replace(response, Boolean.TRUE.toString());
            case WRONG_PIN -> throw new IllegalStateException("The bank rejected the supplied PIN");
            case HAVE_CRC_ERROR, HAVE_IBAN_ERROR -> throw new IllegalArgumentException(
                    "The bank rejected the account identifier"
            );
            default -> {
                // Connection lifecycle and informational callbacks need no response.
            }
        }
    }

    @Override
    public void status(HBCIPassport passport, int statusTag, Object[] data) {
        ExecutionContext context = active.get();
        if (context != null && context.job().getStatus() != JobStatus.AWAITING_USER_ACTION) {
            context.job().update(JobStatus.RUNNING, "Communicating with bank");
        }
    }

    private ExecutionContext requireContext() {
        ExecutionContext context = active.get();
        if (context == null) {
            throw new IllegalStateException("No FinTS execution context is active");
        }
        return context;
    }

    static String selectTanMechanism(String optionsValue, String configured) {
        String[] options = splitOptions(optionsValue);
        if (!isBlank(configured)) {
            String wanted = configured.trim();
            return Arrays.stream(options)
                    .map(GatewayHbciCallback::mechanismCode)
                    .filter(wanted::equals)
                    .findFirst()
                    .orElseThrow(() -> new IllegalArgumentException(
                            "Configured TAN mechanism is not offered by the bank"
                    ));
        }
        for (String option : options) {
            String normalized = option.toLowerCase(Locale.ROOT);
            if (normalized.contains("securego") || normalized.contains("push")
                    || normalized.contains("decoupled") || normalized.contains("app")) {
                return mechanismCode(option);
            }
        }
        return options.length == 0 ? "" : mechanismCode(options[0]);
    }

    static String selectTanMedium(String optionsValue, String configured) {
        String[] options = splitOptions(optionsValue);
        if (!isBlank(configured)) {
            String wanted = configured.trim();
            return Arrays.stream(options)
                    .filter(option -> option.equalsIgnoreCase(wanted))
                    .findFirst()
                    .orElseThrow(() -> new IllegalArgumentException(
                            "Configured TAN medium is not offered by the bank"
                    ));
        }
        return options.length == 0 ? "" : options[0];
    }

    private static String[] splitOptions(String value) {
        if (isBlank(value)) {
            return new String[0];
        }
        return Arrays.stream(value.split("\\|"))
                .map(String::trim)
                .filter(option -> !option.isEmpty())
                .toArray(String[]::new);
    }

    private static String mechanismCode(String option) {
        int separator = option.indexOf(':');
        return separator < 0 ? option.trim() : option.substring(0, separator).trim();
    }

    private static void replace(StringBuffer target, String value) {
        target.replace(0, target.length(), value == null ? "" : value);
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private record ExecutionContext(FintsCredentials credentials, GatewayJob job) {
    }
}
