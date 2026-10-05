package app.finsight.fints.job;

import java.util.UUID;

public class JobNotFoundException extends RuntimeException {
    public JobNotFoundException(UUID id) {
        super("FinTS job not found: " + id);
    }
}
