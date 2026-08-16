use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::RwLock;
pub static MATCH_CONTEXT: RwLock<MatchContext> = RwLock::new(MatchContext {
    home_team_id: 0,
    away_team_id: 0,
    tournament_id: 0,
    stadium_id: 0,
    ball_id: 0,
});
pub static KIT_SERVER: RwLock<Option<KitServer>> = RwLock::new(None);
pub static STADIUM_SERVER: RwLock<Option<StadiumServer>> = RwLock::new(None);
#[derive(Clone, Debug)]
pub struct MatchContext {
    pub home_team_id: u32,
    pub away_team_id: u32,
    pub tournament_id: u32,
    pub stadium_id: u32,
    pub ball_id: u32,
}
pub struct KitServer {
    pub team_kit_map: HashMap<u32, PathBuf>,
}
pub struct StadiumServer {
    pub stadium_map: HashMap<u32, PathBuf>,
}
pub fn set_current_teams(home: u32, away: u32) {
    if let Ok(mut ctx) = MATCH_CONTEXT.write() {
        ctx.home_team_id = home;
        ctx.away_team_id = away;
    }
}
pub fn set_current_stadium(stadium: u32) {
    if let Ok(mut ctx) = MATCH_CONTEXT.write() {
        ctx.stadium_id = stadium;
    }
}
pub fn scan_server_directories(content_root: &Path) {
    let mut ks = KitServer { team_kit_map: HashMap::new() };
    let mut ss = StadiumServer { stadium_map: HashMap::new() };
    let kits_dir = content_root.join("kits");
    if kits_dir.exists() && kits_dir.is_dir() {
        if let Ok(entries) = std::fs::read_dir(kits_dir) {
            for entry in entries.flatten() {
                let p = entry.path();
                if p.is_dir() {
                    if let Some(folder_name) = p.file_name().and_then(|n| n.to_str()) {
                        if let Ok(team_id) = folder_name.parse::<u32>() {
                            ks.team_kit_map.insert(team_id, p);
                        }
                    }
                }
            }
        }
    }
    let stads_dir = content_root.join("stadiums");
    if stads_dir.exists() && stads_dir.is_dir() {
        if let Ok(entries) = std::fs::read_dir(stads_dir) {
            for entry in entries.flatten() {
                let p = entry.path();
                if p.is_dir() {
                    if let Some(folder_name) = p.file_name().and_then(|n| n.to_str()) {
                        if let Ok(stad_id) = folder_name.parse::<u32>() {
                            ss.stadium_map.insert(stad_id, p);
                        }
                    }
                }
            }
        }
    }
    if let Ok(mut lock) = KIT_SERVER.write() {
        *lock = Some(ks);
    }
    if let Ok(mut lock) = STADIUM_SERVER.write() {
        *lock = Some(ss);
    }
}
