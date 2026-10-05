package app.finsight.fints.config;

import app.finsight.fints.hbci.GatewayHbciCallback;
import jakarta.annotation.PostConstruct;
import org.kapott.hbci.manager.HBCIUtils;
import org.springframework.context.annotation.Configuration;

import java.util.Properties;

@Configuration
public class HbciConfiguration {
    private final GatewayHbciCallback callback;

    public HbciConfiguration(GatewayHbciCallback callback) {
        this.callback = callback;
    }

    @PostConstruct
    void initialize() {
        Properties properties = new Properties();
        properties.setProperty("log.loglevel.default", "1");
        properties.setProperty("log.filter", "3");
        properties.setProperty("infoPoint.enabled", "0");
        properties.setProperty("client.passport.PinTan.init", "1");
        properties.setProperty("client.passport.PinTan.checkcert", "1");
        HBCIUtils.init(properties, callback);
    }
}
