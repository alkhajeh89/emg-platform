// Package kmssigner is the production Cloud KMS asymmetric signing adapter
// authorized by ADR-045 S3. It implements the S1 rotationcommit.Signer
// interface shape (ActiveKeyID, SignCommittedDigest) using only Cloud KMS's
// AsymmetricSign RPC, via the minimal AsymmetricSignClient boundary this
// package defines -- it never imports Spanner mutation, GCS witness
// administration, Resource Manager, IAM administration, billing
// administration, or any Cloud KMS key-administration/destruction API (see
// boundary_test.go, which enforces this at the source level, not merely by
// convention).
//
// Private key material never leaves Cloud KMS's boundary and never appears
// anywhere in this package: Signer only ever sends a digest and receives a
// signature back. This package holds no private key bytes, ever.
package kmssigner

import (
	"context"

	"cloud.google.com/go/kms/apiv1/kmspb"
	gax "github.com/googleapis/gax-go/v2"
)

// AsymmetricSignClient is the minimal Cloud KMS boundary this package
// needs: exactly one RPC, AsymmetricSign. It has no GetPublicKey method (a
// signing runtime has no need to retrieve public keys -- that capability
// belongs to keypinning's separate, read-only PublicKeyClient boundary, per
// the IAM permission separation Cloud KMS itself supports:
// cloudkms.cryptoKeyVersions.useToSign vs. .viewPublicKey) and no
// key-administration method of any kind. A *kms.KeyManagementClient
// satisfies this interface without any adapter code, because it already
// implements AsymmetricSign with this exact signature -- but nothing in
// this package ever calls any of that concrete client's other methods, and
// nothing in this package's own exported surface ever hands out a
// reference to the concrete client, only to this narrow interface.
type AsymmetricSignClient interface {
	AsymmetricSign(ctx context.Context, req *kmspb.AsymmetricSignRequest, opts ...gax.CallOption) (*kmspb.AsymmetricSignResponse, error)
}
