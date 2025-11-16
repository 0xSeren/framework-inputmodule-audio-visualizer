{
  description = "Audio visualizer for Framework 16 LED Matrix modules";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    let
      # System-independent outputs
      lib = nixpkgs.lib;
    in
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        pythonEnv = pkgs.python3.withPackages (ps: with ps; [
          numpy
          pyserial
        ]);

        audio-visualizer = pkgs.stdenv.mkDerivation {
          pname = "audio-visualizer";
          version = "1.0.0";

          src = ./.;

          nativeBuildInputs = [ pkgs.makeWrapper ];

          installPhase = ''
            mkdir -p $out/bin $out/lib
            cp audio_visualizer.py $out/lib/

            makeWrapper ${pythonEnv}/bin/python3 $out/bin/audio-visualizer \
              --add-flags "$out/lib/audio_visualizer.py" \
              --prefix PATH : ${lib.makeBinPath [ pkgs.ffmpeg-full pkgs.pulseaudio ]}
          '';

          meta = with lib; {
            description = "Audio visualizer for Framework 16 LED Matrix modules";
            license = licenses.mit;
            platforms = platforms.linux;
          };
        };
      in
      {
        packages = {
          default = audio-visualizer;
          audio-visualizer = audio-visualizer;
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            pythonEnv
            pkgs.ffmpeg-full
            pkgs.pulseaudio
          ];
        };
      }
    ) // {
      # Home Manager module
      homeManagerModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.services.audio-visualizer;
        in
        {
          options.services.audio-visualizer = {
            enable = lib.mkEnableOption "Framework LED Matrix audio visualizer";

            package = lib.mkOption {
              type = lib.types.package;
              default = self.packages.${pkgs.system}.default;
              description = "The audio-visualizer package to use";
            };

            brightness = lib.mkOption {
              type = lib.types.int;
              default = 100;
              description = "LED brightness (0-255)";
            };

            smoothing = lib.mkOption {
              type = lib.types.float;
              default = 0.5;
              description = "Smoothing factor (0.0=instant, 0.9=very smooth)";
            };

            mirror = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Mirror mode: lows in middle, highs at top/bottom";
            };

            mono = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Use mono audio instead of stereo";
            };
          };

          config = lib.mkIf cfg.enable {
            systemd.user.services.audio-visualizer = {
              Unit = {
                Description = "Framework LED Matrix Audio Visualizer";
                After = [ "pipewire.service" "pulseaudio.service" ];
              };

              Service = {
                Type = "simple";
                ExecStart = "${cfg.package}/bin/audio-visualizer"
                  + " --brightness ${toString cfg.brightness}"
                  + " --smoothing ${toString cfg.smoothing}"
                  + lib.optionalString cfg.mirror " --mirror"
                  + lib.optionalString cfg.mono " --mono";
                Restart = "on-failure";
                RestartSec = 5;
              };

              Install = {
                WantedBy = [ "default.target" ];
              };
            };
          };
        };

      # NixOS module (for system-wide installation)
      nixosModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.services.audio-visualizer;
        in
        {
          options.services.audio-visualizer = {
            enable = lib.mkEnableOption "Framework LED Matrix audio visualizer";

            user = lib.mkOption {
              type = lib.types.str;
              description = "User to run the visualizer as";
            };

            package = lib.mkOption {
              type = lib.types.package;
              default = self.packages.${pkgs.system}.default;
              description = "The audio-visualizer package to use";
            };

            brightness = lib.mkOption {
              type = lib.types.int;
              default = 100;
              description = "LED brightness (0-255)";
            };

            smoothing = lib.mkOption {
              type = lib.types.float;
              default = 0.5;
              description = "Smoothing factor (0.0=instant, 0.9=very smooth)";
            };

            mirror = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Mirror mode: lows in middle, highs at top/bottom";
            };

            mono = lib.mkOption {
              type = lib.types.bool;
              default = false;
              description = "Use mono audio instead of stereo";
            };
          };

          config = lib.mkIf cfg.enable {
            # Ensure user has access to serial devices
            users.users.${cfg.user}.extraGroups = [ "dialout" ];

            systemd.user.services.audio-visualizer = {
              description = "Framework LED Matrix Audio Visualizer";
              after = [ "pipewire.service" "pulseaudio.service" ];
              wantedBy = [ "default.target" ];

              serviceConfig = {
                Type = "simple";
                ExecStart = "${cfg.package}/bin/audio-visualizer"
                  + " --brightness ${toString cfg.brightness}"
                  + " --smoothing ${toString cfg.smoothing}"
                  + lib.optionalString cfg.mirror " --mirror"
                  + lib.optionalString cfg.mono " --mono";
                Restart = "on-failure";
                RestartSec = 5;
              };
            };
          };
        };
    };
}
