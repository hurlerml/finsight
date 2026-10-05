package app.finsight.fints.job;

import app.finsight.fints.api.dto.FintsJobRequest;
import app.finsight.fints.service.FintsReadService;
import jakarta.annotation.PreDestroy;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@Service
public class FintsJobService {
    private static final Duration COMPLETED_JOB_TTL = Duration.ofMinutes(10);

    private final Map<UUID, GatewayJob> jobs = new ConcurrentHashMap<>();
    // HBCI4Java stores callback/configuration state at ThreadGroup scope. A
    // single worker avoids cross-connection state leaking between dialogs.
    private final ExecutorService executor = Executors.newSingleThreadExecutor(runnable -> {
        Thread thread = new Thread(runnable, "fints-worker");
        thread.setDaemon(true);
        return thread;
    });
    private final FintsReadService fints;

    public FintsJobService(FintsReadService fints) {
        this.fints = fints;
    }

    public GatewayJob submit(FintsJobRequest request) {
        validateOperation(request);
        GatewayJob job = new GatewayJob();
        jobs.put(job.getId(), job);
        executor.submit(() -> execute(job, request));
        return job;
    }

    public GatewayJob get(UUID id) {
        GatewayJob job = jobs.get(id);
        if (job == null) {
            throw new JobNotFoundException(id);
        }
        return job;
    }

    public void delete(UUID id) {
        jobs.remove(id);
    }

    private void execute(GatewayJob job, FintsJobRequest request) {
        job.update(JobStatus.RUNNING, "Connecting to bank");
        try {
            job.complete(fints.execute(request, job));
        } catch (UnsupportedTanException exception) {
            job.fail("tan_input_required", safeMessage(exception));
        } catch (Exception exception) {
            job.fail("fints_error", safeMessage(exception));
        }
    }

    private static String safeMessage(Exception exception) {
        String message = exception.getMessage();
        if (message == null || message.isBlank()) {
            return "The FinTS operation failed";
        }
        return message.substring(0, Math.min(message.length(), 800));
    }

    private static void validateOperation(FintsJobRequest request) {
        switch (request.operation()) {
            case ACCOUNTS -> {
            }
            case TRANSACTIONS -> {
                if (request.account() == null) {
                    throw new IllegalArgumentException("account is required for transactions");
                }
                if (request.since() == null || request.until() == null) {
                    throw new IllegalArgumentException("since and until are required for transactions");
                }
                if (request.since().isAfter(request.until())) {
                    throw new IllegalArgumentException("since must not be after until");
                }
            }
            case BALANCE -> {
                if (request.account() == null) {
                    throw new IllegalArgumentException("account is required for balance");
                }
            }
        }
    }

    @Scheduled(fixedDelay = 60_000)
    void removeExpiredJobs() {
        Instant cutoff = Instant.now().minus(COMPLETED_JOB_TTL);
        jobs.entrySet().removeIf(entry ->
                entry.getValue().isTerminal() && entry.getValue().getUpdatedAt().isBefore(cutoff)
        );
    }

    @PreDestroy
    void shutdown() {
        executor.shutdownNow();
        jobs.clear();
    }
}
