package com.fixture.xpoverlay;

import com.google.inject.Provides;
import javax.inject.Inject;
import java.time.Instant;
import java.util.EnumMap;
import java.util.Map;
import net.runelite.api.Skill;
import net.runelite.api.events.StatChanged;
import net.runelite.client.config.ConfigManager;
import net.runelite.client.eventbus.Subscribe;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;
import net.runelite.client.ui.overlay.OverlayManager;

@PluginDescriptor(name = "XP Drop Overlay", description = "Recent XP drops overlay", tags = {"xp","overlay"})
public class XpOverlayPlugin extends Plugin {

	@Inject private OverlayManager overlayManager;
	@Inject private XpOverlay overlay;
	@Inject private XpOverlayConfig config;

	private final Map<Skill, Long> lastXp = new EnumMap<>(Skill.class);
	private final Map<Skill, Drop> recentDrops = new EnumMap<>(Skill.class);

	static class Drop {
		final long amount;
		final Instant at;
		Drop(long amount, Instant at) { this.amount = amount; this.at = at; }
	}

	@Provides
	XpOverlayConfig provideConfig(ConfigManager cm) {
		return cm.getConfig(XpOverlayConfig.class);
	}

	@Override
	protected void startUp() {
		overlayManager.add(overlay);
	}

	@Override
	protected void shutDown() {
		overlayManager.remove(overlay);
		lastXp.clear();
		recentDrops.clear();
	}

	@Subscribe
	public void onStatChanged(StatChanged event) {
		Skill skill = event.getSkill();
		long current = event.getXp();
		Long prior = lastXp.put(skill, current);
		if (prior != null && current > prior) {
			recentDrops.put(skill, new Drop(current - prior, Instant.now()));
		}
	}

	public Map<Skill, Drop> getRecentDrops() {
		return recentDrops;
	}

	public int getFadeMillis() {
		return config.fadeMillis();
	}
}
