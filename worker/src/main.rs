use clap::{Parser, Subcommand};

#[derive(Debug, Parser)]
#[command(name = "openmesh-worker", version, about = "OpenMesh-AI worker CLI")]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,
}

#[derive(Debug, Subcommand)]
enum Commands {
    /// Prints worker status
    Health,
}

fn main() {
    let cli = Cli::parse();

    match cli.command {
        Some(Commands::Health) => println!("worker:ok"),
        None => println!("openmesh-worker ready"),
    }
}
