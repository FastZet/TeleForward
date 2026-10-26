//! TeleRoute MTProto Core — Production Binary Entrypoint
//!
//! Initializes structured tracing, SQLite WAL database migrations, background
//! queue & catch-up workers, static SPA serving, and graceful SIGTERM/SIGINT shutdown.

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Instant;
use teleroute_core::{
    api::{build_api_router, AppState},
    storage::init_sqlite_pool,
};
use tower_http::services::{ServeDir, ServeFile};
use tracing::info;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,teleroute=info".into()),
        )
        .init();

    let database_url = std::env::var("DATABASE_URL")
        .unwrap_or_else(|_| "sqlite:///data/teleroute.db?mode=rwc".to_string());
    let static_dir = std::env::var("STATIC_DIR").unwrap_or_else(|_| "./dist".to_string());
    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(3000);

    info!("Initializing SQLite WAL storage pool...");
    let db = init_sqlite_pool(&database_url).await?;

    let state = Arc::new(AppState {
        db,
        started_at: Instant::now(),
    });

    let index_file = format!("{}/index.html", static_dir);
    let app = build_api_router(state).fallback_service(
        ServeDir::new(&static_dir).not_found_service(ServeFile::new(index_file)),
    );

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    info!("TeleRoute MTProto Core listening on http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    info!("Graceful shutdown complete.");
    Ok(())
}

async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    #[cfg(unix)]
    let terminate = async {
        if let Ok(mut sigterm) =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        {
            sigterm.recv().await;
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }
}
